"""Eén schrijfwijze voor energie_type.

`energie_product` en `vtest_contract` droegen "Elektriciteit" en "Gas" met een
hoofdletter — de schrijfwijze van de V-test-export. `netbeheerder_tarief`,
`marktcurve` en `verbruiksprofiel_waarde` droegen "elektriciteit" en "gas".

Een join tussen die twee families op `energie_type` leverde daardoor stil nul
rijen op. Geen fout, geen resultaat: precies de foutklasse waar dit project
tegen ontworpen is. Het viel pas op toen de databank voor het eerst als bron
voor een berekening bekeken werd.

Kleine letters is de doelvorm: `EnergieType` in het domeinmodel is dat al
("elektriciteit" / "gas"), en drie van de vijf tabellen deden het al zo.

De `CHECK`-constraints staan er niet voor de sier. Het probleem ontstond doordat
twee importers los van elkaar naar dezelfde kolomnaam schreven; alleen
normaliseren in de code laat de volgende importer dezelfde fout maken. De
constraint maakt het onmogelijk in plaats van onwaarschijnlijk.

`marktcurve` krijgt bewust geen constraint: het bronwerkboek schrijft de
energievorm in vier vormen door elkaar ("E"/"G", voluit, "Gas TTF",
"Elektriciteit_Injectie") en een onbekende vijfde zou dan een hele publicatie
laten klappen. Daar bewaakt `db audit` het.
"""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

# NULL blijft toegestaan waar de kolom nullable is: "niet ingevuld" is iets
# anders dan "verkeerd geschreven".
_TOEGESTAAN = "energie_type IS NULL OR energie_type IN ('elektriciteit', 'gas')"


def upgrade() -> None:
    # `energie_product` draagt een unieke sleutel waarin energie_type zit. Zouden
    # beide schrijfwijzen naast elkaar bestaan, dan botst deze UPDATE daarop en
    # stopt de migratie — luidruchtig, wat hier het juiste gedrag is.
    for tabel in ("energie_product", "vtest_contract"):
        op.execute(
            f"UPDATE {tabel} SET energie_type = lower(energie_type) "  # noqa: S608
            "WHERE energie_type IS NOT NULL AND energie_type <> lower(energie_type)"
        )

    for tabel in ("energie_product", "vtest_contract", "netbeheerder_tarief"):
        op.create_check_constraint(f"ck_{tabel}_energie_type", tabel, sa.text(_TOEGESTAAN))


def downgrade() -> None:
    for tabel in ("energie_product", "vtest_contract", "netbeheerder_tarief"):
        op.drop_constraint(f"ck_{tabel}_energie_type", tabel, type_="check")
    # De hoofdletterschrijfwijze wordt niet hersteld: welke tabellen ze droegen
    # is een eigenschap van de oude importers, niet van de data.
