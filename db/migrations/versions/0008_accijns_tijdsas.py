"""Tijdsas op de accijnsschijven: geldig_vanaf en geverifieerd.

De bijzondere accijns is geen vast bedrag maar een reeks regimes met een
ingangsdatum. Voor gezinnen ging ze op 01/08/2026 van 47,4811 naar 46,00
EUR/MWh; voor ondernemingen geldt sinds 2022 een heel ander tarief (14,21).
Zonder `geldig_vanaf` slaat de tabel die regimes plat tot één rij per
(energievorm, klantcategorie, schijf) en geeft ze voor elk jaar hetzelfde,
doorgaans verkeerde, antwoord.

`geverifieerd` legt vast of een cijfer tegen een bron gecontroleerd is
(teruggerekend uit vtest.be of gelezen in een officiële publicatie) dan wel
uit een secundaire bron is overgenomen. Dat onderscheid hoort mee te reizen
naar de databank: daar wordt straks op gerekend.

De unieke sleutel bevat de ingangsdatum, zodat twee regimes naast elkaar
kunnen bestaan en een herimport idempotent is.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-31 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TABEL = "overheidsheffing_accijns_schijf"
# De oudste ingangsdatum in config/heffingen/: het regime van de programmawet
# van 25/12/2021, dat voor ondernemingen nog steeds geldt. Bestaande rijen
# krijgen die datum zodat ze niet plots buiten elke periode vallen.
STANDAARD_INGANG = "2022-01-01"


def upgrade() -> None:
    op.add_column(
        TABEL,
        sa.Column("geldig_vanaf", sa.Date(), nullable=True),
    )
    op.add_column(
        TABEL,
        sa.Column(
            "geverifieerd",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # Bestaande rijen dateren van vóór de tijdsas; ze horen bij het oudste
    # regime. Pas daarna mag de kolom verplicht worden.
    # Expliciet naar DATE casten: een bindparameter komt anders als VARCHAR
    # binnen en PostgreSQL weigert die toewijzing aan een date-kolom.
    op.execute(
        sa.text(
            f"UPDATE {TABEL} SET geldig_vanaf = :ingang WHERE geldig_vanaf IS NULL"
        ).bindparams(sa.bindparam("ingang", STANDAARD_INGANG, type_=sa.Date()))
    )
    op.alter_column(TABEL, "geldig_vanaf", nullable=False)

    op.create_unique_constraint(
        "uq_overheidsheffing_accijns_schijf",
        TABEL,
        ["energievorm", "klantcategorie", "van_mwh", "geldig_vanaf"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_overheidsheffing_accijns_schijf", TABEL, type_="unique"
    )
    op.drop_column(TABEL, "geverifieerd")
    op.drop_column(TABEL, "geldig_vanaf")
