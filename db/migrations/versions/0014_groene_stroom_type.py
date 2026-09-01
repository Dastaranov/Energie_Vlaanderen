"""Bewaar het soort groene stroom, niet alleen of het groen is.

vtest.be classificeert elk elektriciteitsproduct als GREEN, GREENLOCAL of
NONE. Dat onderscheid is voor een vergelijker betekenisvol: GREENLOCAL is
lokaal opgewekte groene stroom, en dat is nu net waar een deel van de klanten
op selecteert. Alleen een boolean bewaren zou die twee gelijkschakelen.

`groene_stroom` blijft als boolean staan voor wie enkel wil filteren; het
soort komt ernaast.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-01 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "energie_product",
        sa.Column("groene_stroom_type", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("energie_product", "groene_stroom_type")
