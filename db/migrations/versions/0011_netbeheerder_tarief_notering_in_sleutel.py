"""Tariefnotering hoort bij de sleutel van een netbeheerdertarief.

Dezelfde tariefnaam komt in de VREG-werkboeken voor met verschillende
eenheden. Bij Fluvius Antwerpen staat "Aanvullend capaciteitstarief voor
prosumenten met terugdraaiende teller" twee keer voor klanttype
ELEK_LS_ANA_PRO:

    rij 35   51,54       EUR/kW/jaar
    rij 45    1,8984501  (geen eenheid)

Dat zijn verschillende grootheden, geen dubbels. De unieke sleutel liet
`tariefnotering` weg en verwierp de tweede rij daarom als duplicaat — de
import liep vast op acht van de 192 sleutels, bij elk van de acht
netbeheerders.

De notering wordt hier onderdeel van de sleutel én verplicht met een lege
string in plaats van NULL. Dat laatste is geen detail: PostgreSQL beschouwt
NULLs in een unieke sleutel als onderling verschillend, dus met NULL zouden
twee werkelijk identieke rijen zonder eenheid er allebei in mogen — precies
het stille dubbel dat deze sleutel hoort tegen te houden.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-31 23:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

TABEL = "netbeheerder_tarief"
SLEUTEL = "uq_netbeheerder_tarief"
OPEN_INDEX = "ix_netbeheerder_tarief_open"


def upgrade() -> None:
    op.execute(
        sa.text(f"UPDATE {TABEL} SET tariefnotering = '' WHERE tariefnotering IS NULL")
    )
    op.alter_column(
        TABEL, "tariefnotering", nullable=False, server_default=""
    )

    op.drop_constraint(SLEUTEL, TABEL, type_="unique")
    op.create_unique_constraint(
        SLEUTEL,
        TABEL,
        [
            "netbeheerder_code", "energie_type", "contract_richting",
            "klanttype", "tarieftype", "tariefdetail", "tariefnotering",
            "geldig_van",
        ],
    )

    # De index op de open rij (geldig_tot IS NULL) draagt dezelfde sleutel en
    # moet dus mee: anders zou de SCD2-upsert de rij met de andere eenheid als
    # de open versie van dezelfde rij aanzien en die afsluiten.
    op.drop_index(OPEN_INDEX, table_name=TABEL)
    op.create_index(
        OPEN_INDEX,
        TABEL,
        [
            "netbeheerder_code", "energie_type", "klanttype",
            "tarieftype", "tariefdetail", "tariefnotering",
        ],
        unique=True,
        postgresql_where=sa.text("geldig_tot IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(OPEN_INDEX, table_name=TABEL)
    op.create_index(
        OPEN_INDEX,
        TABEL,
        ["netbeheerder_code", "energie_type", "klanttype", "tarieftype", "tariefdetail"],
        unique=True,
        postgresql_where=sa.text("geldig_tot IS NULL"),
    )
    op.drop_constraint(SLEUTEL, TABEL, type_="unique")
    op.create_unique_constraint(
        SLEUTEL,
        TABEL,
        [
            "netbeheerder_code", "energie_type", "contract_richting",
            "klanttype", "tarieftype", "tariefdetail", "geldig_van",
        ],
    )
    op.alter_column(TABEL, "tariefnotering", nullable=True, server_default=None)
