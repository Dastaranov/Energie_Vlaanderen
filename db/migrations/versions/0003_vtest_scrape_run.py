"""Voeg vtest_scrape_run tabel toe en scrape_run_id FK aan vtest_product

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vtest_scrape_run",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("version_id", sa.String(26), sa.ForeignKey("data_version.version_id"), nullable=False),
        sa.Column("scraped_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("postcode", sa.String(10), nullable=True),
        sa.Column("browser", sa.Text, nullable=True),
        sa.Column("headless", sa.Boolean, nullable=True),
        sa.Column("products_found", sa.Integer, nullable=True),
        sa.Column("dump_bestand", sa.Text, nullable=True),
    )

    op.add_column(
        "vtest_product",
        sa.Column("scrape_run_id", sa.BigInteger, sa.ForeignKey("vtest_scrape_run.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_constraint("vtest_product_scrape_run_id_fkey", "vtest_product", type_="foreignkey")
    op.drop_column("vtest_product", "scrape_run_id")
    op.drop_table("vtest_scrape_run")
