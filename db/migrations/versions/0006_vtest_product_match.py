"""Voeg vtest_product_match toe: best-effort koppeling tussen de live vtest.be-scrape (vreg_id) en de VREG-bulk-export (Handelsnaam/Productnaam)

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-31

De bulk-export (vtest.xlsx / master_vast.csv / master_var_dyn.csv) heeft geen
ID-kolom — enkel Handelsnaam + Productnaam. De koppeling met vreg_id (het
unieke contract-id uit de live scrape) gebeurt daarom via best-effort
tekstmatching (energie_vlaanderen.ingest.vtest.product_matcher), nooit
gegarandeerd volledig. Deze tabel bewaart het resultaat per versie, met
`match_status` zodat mismatches zichtbaar blijven i.p.v. stil te verdwijnen.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vtest_product_match",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("version_id", sa.String(26), nullable=False),
        sa.Column("vreg_id", sa.Text, nullable=False),
        sa.Column("handelsnaam", sa.Text, nullable=True),
        sa.Column("productnaam", sa.Text, nullable=True),
        sa.Column("match_status", sa.Text, nullable=False),
        sa.Column("gekoppeld_op", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.UniqueConstraint("version_id", "vreg_id", name="uq_vtest_product_match_version_vreg"),
        sa.ForeignKeyConstraint(
            ["version_id", "vreg_id"],
            ["vtest_product.version_id", "vtest_product.vreg_id"],
            name="vtest_product_match_vtest_product_fkey",
        ),
    )


def downgrade() -> None:
    op.drop_table("vtest_product_match")
