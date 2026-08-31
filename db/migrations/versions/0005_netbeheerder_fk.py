"""Herstel netbeheerder-referentietabel (afkorting i.p.v. volledige naam) en voeg FK toe aan netwerk_tarief

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-31

netbeheerder.code werd voorheen gevuld met de volledige naam van de
netbeheerder (bv. "Fluvius Antwerpen"), terwijl netwerk_tarief.netbeheerder_code
altijd al de afkorting gebruikte (bv. "FA") — twee losse vocabulaires voor
dezelfde netbeheerders, zonder foreign key ertussen. Deze migratie zaait de
canonieke afkorting-rijen en legt de FK vast.

De databank zit nog volop in ontwikkeling en bestaande data is irrelevant
(bevestigd door de projecteigenaar): in plaats van bestaande volledige-
naam-rijen te herschrijven, wissen we gemeente + netbeheerder gewoon en
herbouwen we ze. Draai na deze migratie opnieuw:
    energievergelijker db import --version <id> --gemeente
om de gemeente-tabel (nu met afkortingen) te hervullen.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# Lokale kopie i.p.v. import van energie_vlaanderen.utility.constants,
# conform Alembic-conventie om migraties los te koppelen van
# applicatiecode die later kan wijzigen.
_DNB_CODES = {
    "Fluvius Antwerpen": "FA", "Fluvius Halle-Vilvoorde": "FHV",
    "Fluvius Imewo": "FI", "Fluvius Kempen": "FK", "Fluvius Limburg": "FL",
    "Fluvius Midden-Vlaanderen": "FMV", "Fluvius West": "FW",
    "Fluvius Zenne-Dijle": "FZD",
}


def upgrade() -> None:
    conn = op.get_bind()

    # Bestaande (volledige-naam-gekeyde) referentiedata is irrelevant in
    # deze ontwikkelfase — schone herstart i.p.v. een in-place data-rewrite.
    conn.execute(sa.text("DELETE FROM gemeente"))
    conn.execute(sa.text("DELETE FROM netbeheerder"))

    for naam, code in _DNB_CODES.items():
        conn.execute(
            sa.text(
                "INSERT INTO netbeheerder (code, naam) VALUES (:code, :naam)"
            ),
            {"code": code, "naam": naam},
        )

    op.create_foreign_key(
        "netwerk_tarief_netbeheerder_code_fkey",
        "netwerk_tarief",
        "netbeheerder",
        ["netbeheerder_code"],
        ["code"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "netwerk_tarief_netbeheerder_code_fkey",
        "netwerk_tarief",
        type_="foreignkey",
    )
    # De gezaaide netbeheerder-rijen (en de leeggemaakte gemeente-tabel)
    # laten we staan — onschadelijke referentiedata, opnieuw op te bouwen
    # via `db import --gemeente`.
