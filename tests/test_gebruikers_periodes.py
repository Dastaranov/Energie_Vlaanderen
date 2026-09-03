"""Tests voor de periodesnijder.

Het scherpste geval van dit project: op 01/08/2026 wijzigde de bijzondere
accijns voor gezinnen van 47,4811 naar 46,00 EUR/MWh (zie
`config/heffingen/bijzondere_accijns_elektriciteit.toml` en de toelichting in
CLAUDE.md). Wie dat jaar in één stuk doorrekent, past één van beide tarieven op
twaalf maanden toe en zit er ongeveer 1,5% naast op de heffingen — zonder
foutmelding.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from energie_vlaanderen.gebruikers.models import (
    Aansluitingspunt,
    Contracttype,
    EnergieType,
    Gebruiker,
    GebruikersError,
    Leveringscontract,
)
from energie_vlaanderen.gebruikers.periodes import (
    Deelperiode,
    contractgrenzen,
    gaten,
    heffingengrenzen,
    indexatiegrenzen,
    snijd,
    tariefjaargrenzen,
)
from energie_vlaanderen.heffingen.repository import HeffingenRepository

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config" / "heffingen"


@pytest.fixture(scope="module")
def heffingen() -> HeffingenRepository:
    return HeffingenRepository.load(CONFIG_DIR)


@pytest.fixture
def punt() -> Aansluitingspunt:
    gebruiker = Gebruiker()
    return Aansluitingspunt(gebruiker.id, EnergieType.ELEKTRICITEIT, "9300", "Aalst")


def contract(punt, leverancier, van, tot=None, soort=Contracttype.VAST):
    return Leveringscontract(punt.id, leverancier, "P", soort, van, tot)


class TestSnijden:
    def test_de_accijnswissel_van_01_08_2026_knipt_het_jaar(self, punt, heffingen):
        """Eén contract, en toch twee deelperiodes.

        De knip komt niet van het contract maar van het heffingenregime: de
        bijzondere accijns voor gezinnen wijzigde op 01/08/2026. 212 + 153 = 365.
        """
        contracten = [contract(punt, "Bolt", date(2026, 1, 1))]
        periodes = snijd(
            date(2026, 1, 1), date(2027, 1, 1), contracten, heffingengrenzen(heffingen)
        )

        assert [p.van for p in periodes] == [date(2026, 1, 1), date(2026, 8, 1)]
        assert [p.dagen for p in periodes] == [212, 153]
        assert sum(p.dagen for p in periodes) == 365
        assert any("accijnsregime" in r for r in periodes[1].redenen)

    def test_een_contractwissel_op_dezelfde_dag_geeft_geen_extra_knip(self, punt, heffingen):
        """Twee oorzaken, één grens — en allebei genoteerd.

        Een lezer moet kunnen zien waaróm het jaar in stukken viel: hier vallen
        de contractwissel en de accijnswissel op dezelfde dag.
        """
        contracten = [
            contract(punt, "Bolt", date(2026, 1, 1), date(2026, 8, 1)),
            contract(punt, "Aspiravi", date(2026, 8, 1)),
        ]
        periodes = snijd(
            date(2026, 1, 1), date(2027, 1, 1), contracten, heffingengrenzen(heffingen)
        )

        assert len(periodes) == 2
        redenen = periodes[1].redenen
        assert any("accijnsregime" in r for r in redenen)
        assert any("contract begint" in r for r in redenen)

    def test_periodes_zijn_half_open_en_sluiten_aaneen(self, punt):
        """[van, tot) — de wisseldag hoort bij de nieuwe periode, niet bij beide.

        Met een inclusieve einddatum zou 01/08 in twee periodes vallen en dubbel
        geteld worden.
        """
        contracten = [
            contract(punt, "A", date(2026, 1, 1), date(2026, 8, 1)),
            contract(punt, "B", date(2026, 8, 1)),
        ]
        periodes = snijd(date(2026, 1, 1), date(2027, 1, 1), contracten)

        for vorige, volgende in zip(periodes, periodes[1:]):
            assert vorige.tot == volgende.van
        wissel = date(2026, 8, 1)
        dekkend = [p for p in periodes if p.van <= wissel < p.tot]
        assert len(dekkend) == 1
        assert dekkend[0].contract.leverancier == "B"

    def test_de_jaarwissel_knipt_altijd(self, punt):
        """Nettarieven worden per tariefjaar goedgekeurd; twee jaren, twee werkboeken."""
        contracten = [contract(punt, "A", date(2025, 1, 1))]
        periodes = snijd(date(2025, 6, 1), date(2026, 6, 1), contracten)
        assert date(2026, 1, 1) in [p.van for p in periodes]

    def test_een_gat_in_de_contracthistoriek_wordt_zichtbaar(self, punt):
        """Geen contract is geen nulkost maar een onbekende kost."""
        contracten = [
            contract(punt, "A", date(2026, 1, 1), date(2026, 4, 1)),
            contract(punt, "B", date(2026, 7, 1)),
        ]
        periodes = snijd(date(2026, 1, 1), date(2026, 10, 1), contracten)
        zonder = gaten(periodes)
        assert len(zonder) == 1
        assert zonder[0].van == date(2026, 4, 1)
        assert zonder[0].tot == date(2026, 7, 1)

    def test_overlappende_contracten_zijn_een_fout_geen_keuze(self, punt):
        """Stil de eerste nemen zou een willekeurige prijs opleveren."""
        contracten = [
            contract(punt, "A", date(2026, 1, 1), date(2026, 9, 1)),
            contract(punt, "B", date(2026, 6, 1)),
        ]
        with pytest.raises(GebruikersError, match="tegelijk"):
            snijd(date(2026, 1, 1), date(2027, 1, 1), contracten)

    def test_een_venster_dat_niet_vooruit_loopt_wordt_geweigerd(self, punt):
        with pytest.raises(GebruikersError):
            snijd(date(2026, 6, 1), date(2026, 1, 1), [])


class TestIndexatie:
    def test_een_variabel_contract_wordt_per_maand_geknipt(self, punt):
        """De indexatieformule neemt per maand een andere waarde aan.

        De V-test-export levert die als maandsnapshot. Zonder deze knip zou één
        maandprijs over de hele contractduur uitgesmeerd worden: een variabel
        contract dat in januari begint en tot september loopt, kreeg dan acht
        maanden lang de januari-index.
        """
        contracten = [contract(punt, "A", date(2026, 1, 1), soort=Contracttype.VARIABEL)]
        periodes = snijd(date(2026, 1, 1), date(2026, 9, 1), contracten)
        assert [p.van.month for p in periodes] == [1, 2, 3, 4, 5, 6, 7, 8]

    def test_een_vast_contract_wordt_niet_per_maand_geknipt(self, punt):
        """Bij een vast contract ligt de prijs juist stil — er is niets te knippen."""
        contracten = [contract(punt, "A", date(2026, 1, 1), soort=Contracttype.VAST)]
        periodes = snijd(date(2026, 1, 1), date(2026, 9, 1), contracten)
        assert len(periodes) == 1

    def test_dynamische_contracten_krijgen_ook_maandgrenzen(self, punt):
        contracten = [contract(punt, "A", date(2026, 1, 1), soort=Contracttype.DYNAMISCH)]
        grenzen = indexatiegrenzen(contracten, date(2026, 1, 1), date(2026, 4, 1))
        assert {g.datum for g in grenzen} == {date(2026, 2, 1), date(2026, 3, 1)}

    def test_alleen_maanden_waarin_het_contract_loopt(self, punt):
        """Buiten de contractduur valt er niets te indexeren.

        Het contract loopt [01/03, 01/05). Maart en april zijn indexatieperiodes
        waarin het loopt; januari, februari en mei tot september niet. Dat 1
        maart ook al een contractgrens is, maakt niet uit — `snijd()` ontdubbelt
        de knippunten en noteert beide redenen.
        """
        contracten = [
            contract(punt, "A", date(2026, 3, 1), date(2026, 5, 1), soort=Contracttype.VARIABEL)
        ]
        grenzen = indexatiegrenzen(contracten, date(2026, 1, 1), date(2026, 9, 1))
        assert {g.datum for g in grenzen} == {date(2026, 3, 1), date(2026, 4, 1)}


class TestGrenzen:
    def test_contractgrenzen_dragen_begin_en_einde(self, punt):
        grenzen = contractgrenzen([contract(punt, "A", date(2026, 1, 1), date(2026, 8, 1))])
        assert {g.datum for g in grenzen} == {date(2026, 1, 1), date(2026, 8, 1)}

    def test_tariefjaargrenzen_dekken_elk_jaar_in_het_venster(self):
        grenzen = tariefjaargrenzen(date(2025, 6, 1), date(2027, 3, 1))
        assert {g.datum for g in grenzen} == {
            date(2025, 1, 1),
            date(2026, 1, 1),
            date(2027, 1, 1),
        }

    def test_heffingengrenzen_bevatten_de_wissel_van_01_08_2026(self, heffingen):
        """De datum die dit hele mechanisme rechtvaardigt."""
        grenzen = heffingengrenzen(heffingen, "elektriciteit")
        assert date(2026, 8, 1) in {g.datum for g in grenzen}


class TestDeelperiode:
    def test_aandeel_wordt_in_dagen_gerekend(self, punt):
        """Maanden zijn ongelijk lang en een contractwissel valt zelden op een maandgrens."""
        periode = Deelperiode(date(2026, 1, 1), date(2026, 8, 1), None)
        assert periode.dagen == 212
        assert periode.aandeel_van(365) * 365 == 212

    def test_een_periode_die_niet_vooruit_loopt_bestaat_niet(self):
        with pytest.raises(GebruikersError):
            Deelperiode(date(2026, 8, 1), date(2026, 1, 1), None)
