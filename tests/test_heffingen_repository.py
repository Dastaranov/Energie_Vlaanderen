"""Tests voor HeffingenRepository — laadt de échte config/heffingen/*.toml
(kleine, stabiele masterdatabestanden, geen synthetische fixtures nodig)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from energie_vlaanderen.heffingen.repository import HeffingenError, HeffingenRepository

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config" / "heffingen"


pytestmark = pytest.mark.masterdata


@pytest.fixture(scope="module")
def repo() -> HeffingenRepository:
    return HeffingenRepository.load(CONFIG_DIR)


class TestAccijnsParsing:
    """De accijnstabellen dragen een tijdsas: de bijzondere accijns werd door
    de hervorming van 2023 ruim verdrievoudigd en daalt sinds 01/08/2026
    opnieuw. Een tabel zonder ingangsdatum gaf voor elk jaar hetzelfde,
    doorgaans verkeerde antwoord."""

    def test_beide_energievormen_geladen(self, repo: HeffingenRepository):
        assert set(repo.accijns_tabellen()) == {"elektriciteit", "aardgas"}

    def test_residentieel_elektriciteitstarief_is_het_gekalibreerde_tarief(
        self, repo: HeffingenRepository
    ):
        # 46,00 EUR/MWh excl. btw is teruggerekend uit vtest.be zelf
        # (7 verbruikspunten, residu 0,00 EUR) en komt overeen met de
        # 48,76 EUR/MWh incl. btw die de officiële communicatie noemt.
        (schijf,) = repo.accijns_schijven(
            "elektriciteit", "niet_zakelijk", date(2026, 8, 31)
        )
        assert schijf.bijzondere_accijns_eur_mwh == D("46.0000")
        assert isinstance(schijf.bijzondere_accijns_eur_mwh, D)

    def test_residentiele_energiebijdrage_is_1_9261(self, repo: HeffingenRepository):
        """Deze assertie stond op 0, en dat was fout.

        De verantwoording luidde "bevestigd door vtest.be, dat deze post op
        0,00 EUR zet". vtest.be *toont* die post inderdaad niet — maar dat is
        iets anders dan dat ze nul is.

        Artikel 39 van de programmawet van 25/12/2021 zet voor niet-zakelijk
        gebruik in elke verbruiksschijf "bijdrage op de energie: 1,9261 euro
        per MWh" (zie `docs/research/tarief bijzonder accijns.md`, met de
        wettekst). Een echte ENGIE-eindafrekening rekent hem ook aan: 4,09 EUR
        op 2.124 kWh en 9,04 EUR op 4.693 kWh, allebei 1,9261 EUR/MWh, als
        aparte regel naast de bijzondere accijns.

        Een wettekst en een betaalde factuur die elkaar bevestigen wegen hier
        zwaarder dan een vergelijkingstool die de post weglaat.
        """
        (schijf,) = repo.accijns_schijven(
            "elektriciteit", "niet_zakelijk", date(2026, 8, 31)
        )
        assert schijf.energiebijdrage_eur_mwh == D("1.9261")

    def test_de_bijdrage_op_de_energie_is_gelijk_voor_gezin_en_onderneming(
        self, repo: HeffingenRepository
    ):
        """De wet maakt hier geen onderscheid; de bijzondere accijns wel.

        Programmawet art. 39 noemt 1,9261 EUR/MWh zowel onder "zakelijk
        gebruik, aansluiting <= 1 kV" als onder "niet-zakelijk gebruik". Alleen
        boven 1 kV staat de bijdrage op nul.
        """
        (gezin,) = repo.accijns_schijven(
            "elektriciteit", "niet_zakelijk", date(2026, 8, 31)
        )
        zakelijk = repo.accijns_schijven(
            "elektriciteit", "zakelijk_laagspanning", date(2026, 8, 31)
        )
        assert gezin.energiebijdrage_eur_mwh == zakelijk[0].energiebijdrage_eur_mwh
        assert gezin.bijzondere_accijns_eur_mwh != zakelijk[0].bijzondere_accijns_eur_mwh

    def test_ouder_regime_blijft_bereikbaar(self, repo: HeffingenRepository):
        (schijf,) = repo.accijns_schijven(
            "elektriciteit", "niet_zakelijk", date(2026, 7, 31)
        )
        assert schijf.bijzondere_accijns_eur_mwh == D("47.4811")

    def test_regimes_worden_niet_vermengd(self, repo: HeffingenRepository):
        """Alle teruggegeven schijven horen bij één ingangsdatum."""
        schijven = repo.accijns_schijven(
            "elektriciteit", "zakelijk_laagspanning", date(2026, 8, 31)
        )
        assert len({s.geldig_vanaf for s in schijven}) == 1

    def test_datum_voor_de_masterdata_faalt_hard(self, repo: HeffingenRepository):
        # Liever stoppen dan met een tarief rekenen dat toen niet gold.
        with pytest.raises(HeffingenError, match="2023-07-01"):
            repo.accijns_schijven("elektriciteit", "niet_zakelijk", date(2020, 1, 1))


class TestProgressieveBerekening:
    def test_residentiele_elektriciteit_is_vlak(self, repo: HeffingenRepository):
        """In het huishoudelijke bereik is er geen schijfovergang.

        De kalibratie mat een perfect rechte kostenfunctie van 1.000 tot
        25.000 kWh; de wettelijke grenzen op 3 en 20 MWh vallen samen qua
        tarief.
        """
        for kwh in (D("1000"), D("3434"), D("25000")):
            bijzondere, energiebijdrage = repo.bereken_accijns_en_energiebijdrage(
                "elektriciteit", "niet_zakelijk", kwh, date(2026, 8, 31)
            )
            assert bijzondere == kwh / D("1000") * D("46.0000")
            # De bijdrage op de energie is eveneens vlak: de wet noemt
            # 1,9261 EUR/MWh in élke schijf.
            assert energiebijdrage == kwh / D("1000") * D("1.9261")

    def test_gemiddeld_gezin_komt_overeen_met_vtest(self, repo: HeffingenRepository):
        """Het profiel dat vtest.be zelf als standaard hanteert: 3.434 kWh.

        vtest.be rapporteert daarvoor 157,96 EUR bijzondere accijns excl. btw.
        """
        bijzondere, _ = repo.bereken_accijns_en_energiebijdrage(
            "elektriciteit", "niet_zakelijk", D("3434"), date(2026, 8, 31)
        )
        assert bijzondere.quantize(D("0.01")) == D("157.96")

    def test_aardgas_over_de_schijfgrens(self, repo: HeffingenRepository):
        """Aardgas kent wél een knik, op 12 MWh."""
        onder = repo.bereken_accijns_en_energiebijdrage(
            "aardgas", "niet_zakelijk", D("12000"), date(2026, 8, 31)
        )[0]
        boven = repo.bereken_accijns_en_energiebijdrage(
            "aardgas", "niet_zakelijk", D("13000"), date(2026, 8, 31)
        )[0]
        marginaal = (boven - onder) * D("1000") / D("1000")
        basis = onder / D("12")
        assert marginaal > basis

    def test_gemiddeld_gasverbruik_komt_overeen_met_vtest(self, repo: HeffingenRepository):
        """vtest.be rekent 171,28 EUR excl. btw voor zijn standaard 16.262 kWh."""
        bijzondere, _ = repo.bereken_accijns_en_energiebijdrage(
            "aardgas", "niet_zakelijk", D("16262"), date(2026, 8, 31)
        )
        assert abs(bijzondere - D("171.28")) <= D("0.05")

    def test_onbekende_klantcategorie_faalt_hard(self, repo: HeffingenRepository):
        with pytest.raises(HeffingenError, match="onbekende_categorie"):
            repo.bereken_accijns_en_energiebijdrage(
                "elektriciteit", "onbekende_categorie", D("1000"), date(2026, 8, 31)
            )

    def test_onbekende_energievorm_faalt_hard(self, repo: HeffingenRepository):
        with pytest.raises(HeffingenError, match="stookolie"):
            repo.bereken_accijns_en_energiebijdrage(
                "stookolie", "niet_zakelijk", D("1000"), date(2026, 8, 31)
            )


class TestEnergiefonds:
    def test_2026_niet_residentieel(self, repo: HeffingenRepository):
        assert repo.energiefonds_per_jaar("laag", "niet_residentieel", 2026) == D("10.07") * D("12")

    def test_2026_residentieel_is_nul(self, repo: HeffingenRepository):
        assert repo.energiefonds_per_jaar("laag", "residentieel", 2026) == D("0")

    def test_2026_hoogspanning(self, repo: HeffingenRepository):
        assert repo.energiefonds_per_jaar("hoog", "", 2026) == D("1120.66") * D("12")

    def test_onbekend_jaar_faalt_hard(self, repo: HeffingenRepository):
        with pytest.raises(HeffingenError, match="2099"):
            repo.energiefonds_per_jaar("laag", "residentieel", 2099)


class TestBtw:
    def test_elektriciteit_zes_procent(self, repo: HeffingenRepository):
        assert repo.btw_percentage("elektriciteit") == D("0.06")

    def test_energiefonds_bijdrage_vrijgesteld(self, repo: HeffingenRepository):
        assert repo.btw_percentage("bijdrage_energiefonds") == D("0")

    def test_onbekend_component_faalt_hard(self, repo: HeffingenRepository):
        with pytest.raises(HeffingenError):
            repo.btw_percentage("onbekend")
