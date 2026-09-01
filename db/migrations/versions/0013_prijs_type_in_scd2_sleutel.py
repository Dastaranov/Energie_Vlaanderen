"""Prijstype hoort bij de sleutel van een producttarief.

Een product kan bij dezelfde leverancier onder dezelfde naam zowel variabel
als dynamisch aangeboden worden — bij Bolt is "Bolt Variabel" allebei. In de
export zijn dat aparte rijen met een eigen indexatieformule; in de databank
delen ze één energie_product, want de identiteit daarvan is (leverancier,
naam, energievorm, segment).

De SCD2-sleutel van de tariefrijen was (product_id, meter_type), zonder
prijs_type. De twee prijstypes verdrongen elkaars historiek daardoor: het
eerste bouwde de reeks op tot de laatste maand, en het tweede werd vanaf de
eerste maand als terugwerkend afgewezen. Bij deze dataset raakte dat 62 van
de 765 productidentiteiten en 624 tariefrijen.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-01 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

TABELLEN = ("tarief_afname", "tarief_injectie")


def upgrade() -> None:
    for tabel in TABELLEN:
        index = f"ix_{tabel}_open"
        op.drop_index(index, table_name=tabel)
        op.create_index(
            index,
            tabel,
            ["product_id", "meter_type", "prijs_type"],
            unique=True,
            postgresql_where=sa.text("geldig_tot IS NULL"),
        )


def downgrade() -> None:
    for tabel in TABELLEN:
        index = f"ix_{tabel}_open"
        op.drop_index(index, table_name=tabel)
        op.create_index(
            index,
            tabel,
            ["product_id", "meter_type"],
            unique=True,
            postgresql_where=sa.text("geldig_tot IS NULL"),
        )
