"""Splits product_component in leverancier_product + product_component; voegt jaar toe aan netwerk_tarief

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Nieuwe tabel: leverancier_product (product-header zonder componentherhalingen)
    op.create_table(
        "leverancier_product",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("version_id", sa.String(26), sa.ForeignKey("data_version.version_id"), nullable=False),
        sa.Column("jaar", sa.SmallInteger, nullable=False),
        sa.Column("maand", sa.SmallInteger, nullable=False),
        sa.Column("segment", sa.Text, nullable=False),
        sa.Column("energie_type", sa.Text, nullable=False),
        sa.Column("contract_richting", sa.Text, nullable=False),
        sa.Column("leverancier", sa.Text, nullable=False),
        sa.Column("product", sa.Text, nullable=False),
        sa.Column("bron_type", sa.Text, nullable=False),
        sa.Column("bron_bestand", sa.Text, nullable=True),
        sa.Column("source_sheet", sa.Text, nullable=True),
        sa.UniqueConstraint(
            "version_id", "energie_type", "contract_richting", "leverancier", "product",
            "jaar", "maand", "segment",
            name="uq_leverancier_product",
        ),
    )
    op.create_index(
        "ix_leverancier_product_lookup",
        "leverancier_product",
        ["version_id", "energie_type", "leverancier", "product", "jaar", "maand"],
    )

    # 2. product_component droppen en opnieuw aanmaken met nieuwe structuur
    op.drop_table("product_component")
    op.create_table(
        "product_component",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("leverancier_product_id", sa.BigInteger, sa.ForeignKey("leverancier_product.id"), nullable=False),
        sa.Column("component_code", sa.Text, nullable=False),
        sa.Column("component_label", sa.Text, nullable=True),
        sa.Column("eenheid", sa.Text, nullable=True),
        sa.Column("btw_code", sa.Text, nullable=True),
        sa.Column("prijs", sa.Numeric(14, 6), nullable=True),
        sa.Column("a", sa.Numeric(12, 6), nullable=True),
        sa.Column("b", sa.Numeric(12, 6), nullable=True),
        sa.Column("c", sa.Numeric(12, 6), nullable=True),
        sa.Column("d", sa.Numeric(12, 6), nullable=True),
        sa.Column("z", sa.Numeric(12, 6), nullable=True),
        sa.Column("index_naam_a", sa.Text, nullable=True),
        sa.Column("index_naam_b", sa.Text, nullable=True),
        sa.Column("index_naam_c", sa.Text, nullable=True),
        sa.Column("index_naam_d", sa.Text, nullable=True),
        sa.Column("index_waarde_a", sa.Numeric(14, 6), nullable=True),
        sa.Column("index_waarde_b", sa.Numeric(14, 6), nullable=True),
        sa.Column("index_waarde_c", sa.Numeric(14, 6), nullable=True),
        sa.Column("index_waarde_d", sa.Numeric(14, 6), nullable=True),
        sa.Column("source_row", sa.Integer, nullable=True),
    )

    # 3. jaar toevoegen aan netwerk_tarief + unieke constraint herbouwen
    op.add_column("netwerk_tarief", sa.Column("jaar", sa.SmallInteger, nullable=True))
    op.drop_constraint("uq_netwerk_tarief", "netwerk_tarief", type_="unique")
    op.create_unique_constraint(
        "uq_netwerk_tarief",
        "netwerk_tarief",
        ["version_id", "netbeheerder_code", "energie_type", "contract_richting",
         "klanttype", "tarieftype", "tariefdetail", "jaar"],
    )


def downgrade() -> None:
    # netwerk_tarief terugzetten
    op.drop_constraint("uq_netwerk_tarief", "netwerk_tarief", type_="unique")
    op.drop_column("netwerk_tarief", "jaar")
    op.create_unique_constraint(
        "uq_netwerk_tarief",
        "netwerk_tarief",
        ["version_id", "netbeheerder_code", "energie_type", "contract_richting",
         "klanttype", "tarieftype", "tariefdetail"],
    )

    # product_component terugzetten (zonder data)
    op.drop_table("product_component")
    op.create_table(
        "product_component",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("version_id", sa.String(26), sa.ForeignKey("data_version.version_id"), nullable=False),
        sa.Column("jaar", sa.SmallInteger, nullable=False),
        sa.Column("maand", sa.SmallInteger, nullable=False),
        sa.Column("segment", sa.Text, nullable=False),
        sa.Column("energie_type", sa.Text, nullable=False),
        sa.Column("contract_richting", sa.Text, nullable=False),
        sa.Column("leverancier", sa.Text, nullable=False),
        sa.Column("product", sa.Text, nullable=False),
        sa.Column("bron_type", sa.Text, nullable=False),
        sa.Column("component", sa.Text, nullable=False),
        sa.Column("component_label", sa.Text, nullable=True),
        sa.Column("prijs", sa.Numeric(14, 6), nullable=True),
        sa.Column("a", sa.Numeric(12, 6), nullable=True),
        sa.Column("b", sa.Numeric(12, 6), nullable=True),
        sa.Column("c", sa.Numeric(12, 6), nullable=True),
        sa.Column("d", sa.Numeric(12, 6), nullable=True),
        sa.Column("z", sa.Numeric(12, 6), nullable=True),
        sa.Column("index_naam_a", sa.Text, nullable=True),
        sa.Column("index_naam_b", sa.Text, nullable=True),
        sa.Column("index_naam_c", sa.Text, nullable=True),
        sa.Column("index_naam_d", sa.Text, nullable=True),
        sa.Column("index_waarde_a", sa.Numeric(14, 6), nullable=True),
        sa.Column("index_waarde_b", sa.Numeric(14, 6), nullable=True),
        sa.Column("index_waarde_c", sa.Numeric(14, 6), nullable=True),
        sa.Column("index_waarde_d", sa.Numeric(14, 6), nullable=True),
        sa.Column("source_sheet", sa.Text, nullable=True),
        sa.Column("source_row", sa.Integer, nullable=True),
        sa.Column("bron_bestand", sa.Text, nullable=True),
    )

    op.drop_index("ix_leverancier_product_lookup", "leverancier_product")
    op.drop_table("leverancier_product")
