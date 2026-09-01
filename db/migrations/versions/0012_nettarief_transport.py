"""Vervoerstarief aardgas (Fluxys) als masterdata in de databank.

vtest.be splitst de gasnettarieven in vier posten. Drie komen uit de
VREG-distributiewerkboeken en klopten al exact voor alle acht netbeheerders.
De vierde — het vervoerstarief van Fluxys — staat in geen enkel werkboek: het
is geen distributietarief maar een doorrekening. Het ontbrak daardoor
volledig, wat elke gasfactuur ongeveer 25 EUR per jaar te laag maakte.

Zelfde vorm als de accijnstabel: een tijdsas per tarief en een
verificatievlag, zodat een regimewissel niet stil een ouder cijfer laat staan
en zodat zichtbaar blijft waartegen een cijfer gecontroleerd is.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-01 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nettarief_transport",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("energievorm", sa.Text(), nullable=False),
        sa.Column("klantcategorie", sa.Text(), nullable=False),
        sa.Column("eur_per_kwh", sa.Numeric(precision=12, scale=8), nullable=False),
        sa.Column("geldig_vanaf", sa.Date(), nullable=False),
        sa.Column(
            "geverifieerd", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("bron", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "energievorm", "klantcategorie", "geldig_vanaf",
            name="uq_nettarief_transport",
        ),
    )


def downgrade() -> None:
    op.drop_table("nettarief_transport")
