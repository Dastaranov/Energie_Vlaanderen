"""Merknaam en juridische entiteit uit elkaar halen.

VREG schrijft de leverancier soms als merknaam en soms als merknaam met de
juridische entiteit erachter: "ENGIE" naast "ENGIE (handelsnaam van
Electrabel)", "Mega" naast "Mega (handelsnaam van Power Online)". De
bulk-export gebruikt beide vormen door elkaar, de live scrape van vtest.be
vrijwel altijd de lange.

Zonder splitsing worden dat twee leveranciers en raken de producten van één
leverancier over twee records verdeeld — precies waar de vreg_id-koppeling op
stukliep. Het achtervoegsel is echter geen ruis: het zegt onder welke
juridische entiteit een merk verkoopt, en dat is bruikbare informatie. Dus
niet weggooien maar in een eigen kolom.

De merknaam wordt daarmee de identiteit (uniek op lower(naam), zie 0009) en de
entiteit een eigenschap. Merken die dezelfde entiteit delen maar los verkocht
worden — 'Wind voor "A"' en Aspiravi Energy, of de zeven merken van Energy
Together — blijven terecht aparte leveranciers.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-31 23:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

# Hetzelfde patroon als utility.normalizer.split_leveranciersnaam, hier in SQL
# zodat bestaande rijen meteen meegaan.
SUFFIX_PATROON = r"\s*\(handelsnaam van ([^)]+)\)\s*$"


def upgrade() -> None:
    op.add_column(
        "leverancier",
        sa.Column("juridische_entiteit", sa.Text(), nullable=True),
    )

    # Bestaande namen splitsen: entiteit naar de nieuwe kolom, merknaam blijft.
    op.execute(
        sa.text(
            f"""
            UPDATE leverancier
            SET juridische_entiteit = substring(naam from '{SUFFIX_PATROON}'),
                naam = regexp_replace(naam, '{SUFFIX_PATROON}', '')
            WHERE naam ~ '{SUFFIX_PATROON}'
            """
        )
    )

    # Het splitsen kan nieuwe dubbels maken ("ENGIE" bestond mogelijk al naast
    # "ENGIE (handelsnaam van Electrabel)"). Voeg die samen zoals in 0009:
    # producten verhangen naar de laagste id, de rest verwijderen. De
    # entiteitwaarde van de rij die blijft, wordt aangevuld als ze leeg was.
    op.execute(
        sa.text(
            """
            WITH doelen AS (
                SELECT lower(naam) AS sleutel, min(id) AS behoud_id
                FROM leverancier
                GROUP BY lower(naam)
                HAVING count(*) > 1
            )
            UPDATE leverancier b
            SET juridische_entiteit = COALESCE(
                b.juridische_entiteit,
                (SELECT max(a.juridische_entiteit)
                 FROM leverancier a, doelen d
                 WHERE lower(a.naam) = d.sleutel AND d.behoud_id = b.id)
            )
            FROM doelen d
            WHERE b.id = d.behoud_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH doelen AS (
                SELECT lower(naam) AS sleutel, min(id) AS behoud_id
                FROM leverancier
                GROUP BY lower(naam)
                HAVING count(*) > 1
            )
            UPDATE energie_product ep
            SET leverancier_id = d.behoud_id
            FROM leverancier l
            JOIN doelen d ON lower(l.naam) = d.sleutel
            WHERE ep.leverancier_id = l.id AND l.id <> d.behoud_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM leverancier l
            USING (
                SELECT lower(naam) AS sleutel, min(id) AS behoud_id
                FROM leverancier
                GROUP BY lower(naam)
                HAVING count(*) > 1
            ) d
            WHERE lower(l.naam) = d.sleutel AND l.id <> d.behoud_id
            """
        )
    )


def downgrade() -> None:
    # De merknamen weer aanvullen met het achtervoegsel waar een entiteit
    # bekend is, zodat de oude schrijfwijze terugkomt.
    op.execute(
        sa.text(
            """
            UPDATE leverancier
            SET naam = naam || ' (handelsnaam van ' || juridische_entiteit || ')'
            WHERE juridische_entiteit IS NOT NULL
            """
        )
    )
    op.drop_column("leverancier", "juridische_entiteit")
