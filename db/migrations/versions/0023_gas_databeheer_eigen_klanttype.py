"""Haal de gas-databeheertarieven weg bij de tariefgroep waar ze niet horen.

Databeheer bij aardgas hangt aan de **metersoort**, niet aan de tariefgroep.
Het VREG-werkboek zet de drie tarieven (AMR, MMR, Jaaropname) onder de kop
"3) Tarief databeheer", elk met één bedrag in één willekeurige kolom: AMR in de
T5-kolom, MMR en Jaaropname in de T1-kolom. Met de vaste kolomkaart van de
normalizer kregen ze daardoor `GAS_T5` respectievelijk `GAS_T1` als klanttype —
alsof ze alleen voor díé tariefgroep golden.

Gevolg: een gezin in T2 (5.001-150.000 kWh) vond geen databeheertarief en
betaalde er dus geen. Op de referentiefactuur scheelde dat 17,62 EUR op een
distributiekost van 196,24 — bijna 9%, en niets faalde. Dezelfde klasse als
`ELEK_LS_DC`: een tarief dat bestaat, maar aan de verkeerde sleutel hangt.

De normalizer geeft ze nu een eigen klanttype (`GAS_DBH_AMR`, `GAS_DBH_MMR`,
`GAS_DBH_JAAROPNAME`). Een herimport voegt die rijen toe, maar verwijdert de
oude niet: de SCD2-upsert kent alleen invoegen en afsluiten, geen verhuizen.
Deze migratie ruimt daarom op wat achterblijft.

**Alleen de verhuisde rijen, en herkenbaar aan hun omschrijving.** Er wordt niet
op klanttype alleen verwijderd — T1 en T5 dragen ook hun eigen, juiste tarieven
(vaste term, proportionele term, ODV). De omschrijving is wat deze drie
onderscheidt.

**En de naamloze ODV-rijen.** Dezelfde normalizerwijziging geeft het
ODV-tarief eindelijk een naam: "II. Het tarief openbaredienstverplichtingen"
stond in kolom 0 in plaats van kolom 1, waardoor 24 rijen per tariefjaar een
lege `Tariefdetail` droegen. Ook hier verhuist de sleutel, en ook hier laat de
SCD2-upsert de oude rij staan — naast de nieuwe, met hetzelfde bedrag en
dezelfde eenheid. Twee rijen voor één tarief is erger dan een naamloze rij: een
opzoeking op eenheid vindt er dan twee en neemt de eerste.

Terugdraaien zet ze niet terug. Dat zou de fout herstellen, en de rijen staan
hoe dan ook één herimport later weer op hun plaats; het werkboek is de bron en
blijft bewaard.
"""
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. de databeheertarieven die aan een tariefgroep hingen
    op.execute(
        """
        delete from netbeheerder_tarief
         where energie_type = 'gas'
           and klanttype in ('GAS_T1', 'GAS_T5')
           and (
                 tariefdetail in ('AMR', 'MMR')
              or tariefdetail like 'Jaaropname%'
           )
        """
    )
    # 2. de naamloze ODV-rijen, die nu een naam dragen
    op.execute(
        """
        delete from netbeheerder_tarief
         where energie_type = 'gas'
           and coalesce(tariefdetail, '') = ''
        """
    )


def downgrade() -> None:
    # Bewust leeg: zie de toelichting hierboven.
    pass
