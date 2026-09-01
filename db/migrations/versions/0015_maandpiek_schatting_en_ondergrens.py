"""Scheid de geschatte maandpiek van de wettelijke ondergrens.

`geschatte_maandpiek_kw` stond op 2,5 kW. Dat is niet de piek van een
gemiddeld gezin maar de wettelijke bodem van het capaciteitstarief: het getal
waaronder er niet gerekend wórdt. Als standaardwaarde betekende het dat elk
profiel zonder eigen meetdata per definitie op die bodem uitkwam en dus
systematisch te goedkoop rekende — ongeveer 86 EUR per jaar.

Twee betekenissen die in één kolom zaten, staan nu in twee kolommen:

- `geschatte_maandpiek_kw` wordt 4,218 kW, de piek waarmee vtest.be zijn
  standaardwoning doorrekent. Teruggerekend uit de gescrapete
  capaciteitstarieven van alle acht netbeheerders op 2026-08-31.
- `minimum_maandpiek_kw` wordt 2,5 kW en draagt voortaan de ondergrens.

De precisie gaat van Numeric(6, 2) naar Numeric(7, 3), anders zou 4,218 bij
het opslaan stil 4,22 worden — het soort afronding dat pas maanden later in
een factuur opvalt.

Bestaande rijen die nog exact op de oude standaardwaarde 2,50 staan, hebben
die waarde niet gekozen maar geërfd; die worden meegenomen naar 4,218. Een
profiel met een andere waarde blijft ongemoeid: dat is iemands eigen invoer.

In de praktijk raakt die datamigratie vandaag niets — `gebruiker` is nog een
lege scaffold-tabel. Ze staat er voor het geval deze migratie later op een
databank draait waar wel profielen in staan.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-01 13:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gebruiker",
        sa.Column(
            "minimum_maandpiek_kw",
            sa.Numeric(7, 3),
            nullable=True,
            server_default="2.5",
        ),
    )
    op.alter_column(
        "gebruiker",
        "geschatte_maandpiek_kw",
        type_=sa.Numeric(7, 3),
        existing_type=sa.Numeric(6, 2),
        server_default="4.218",
    )
    # Alleen de rijen die de oude standaardwaarde nooit bewust gekozen hebben.
    op.execute(
        "UPDATE gebruiker SET geschatte_maandpiek_kw = 4.218 "
        "WHERE geschatte_maandpiek_kw = 2.5"
    )
    op.execute("UPDATE gebruiker SET minimum_maandpiek_kw = 2.5")


def downgrade() -> None:
    # De ondergrens verdwijnt weer in de schatting; wie op 4,218 stond, stond
    # daarvoor op 2,5.
    op.execute(
        "UPDATE gebruiker SET geschatte_maandpiek_kw = 2.5 "
        "WHERE geschatte_maandpiek_kw = 4.218"
    )
    op.alter_column(
        "gebruiker",
        "geschatte_maandpiek_kw",
        type_=sa.Numeric(6, 2),
        existing_type=sa.Numeric(7, 3),
        server_default="2.5",
    )
    op.drop_column("gebruiker", "minimum_maandpiek_kw")
