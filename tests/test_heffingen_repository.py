"""Tests voor HeffingenRepository — laadt de échte config/heffingen/*.toml
(kleine, stabiele masterdatabestanden, geen synthetische fixtures nodig)."""
from __future__ import annotations

from decimal import Decimal as D
from pathlib import Path

import pytest

from energie_vlaanderen.heffingen.repository import HeffingenError, HeffingenRepository

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config" / "heffingen"


@pytest.fixture(scope="module")
def repo() -> HeffingenRepository:
    return HeffingenRepository.load(CONFIG_DIR)


class TestAccijnsParsing:
    def test_alle_achttien_schijven_geladen(self, repo: HeffingenRepository):
        tabel = repo._accijns["elektriciteit"]
        assert len(tabel.schijven) == 18
        for categorie in ("niet_zakelijk", "zakelijk_laagspanning", "zakelijk_hoogspanning"):
            assert sum(1 for s in tabel.schijven if s.klantcategorie == categorie) == 6

    def test_bedragen_zijn_decimal(self, repo: HeffingenRepository):
        tabel = repo._accijns["elektriciteit"]
        eerste = next(
            s for s in tabel.schijven
            if s.klantcategorie == "niet_zakelijk" and s.van_mwh == D("0")
        )
        assert eerste.bijzondere_accijns_eur_mwh == D("13.60")
        assert isinstance(eerste.bijzondere_accijns_eur_mwh, D)
        assert eerste.tot_mwh == D("20")

    def test_hoogste_schijf_heeft_geen_bovengrens(self, repo: HeffingenRepository):
        tabel = repo._accijns["elektriciteit"]
        hoogste = next(
            s for s in tabel.schijven
            if s.klantcategorie == "niet_zakelijk" and s.van_mwh == D("100000")
        )
        assert hoogste.tot_mwh is None


class TestProgressieveBerekening:
    def test_verbruik_binnen_eerste_schijf(self, repo: HeffingenRepository):
        bijzondere, energiebijdrage = repo.bereken_accijns_en_energiebijdrage(
            "elektriciteit", "niet_zakelijk", jaarverbruik_kwh=D("5000")
        )
        # 5 MWh volledig in schijf 0-20 MWh: 5 * 13.60 / 5 * 1.9261
        assert bijzondere == D("5") * D("13.60")
        assert energiebijdrage == D("5") * D("1.9261")

    def test_verbruik_over_schijfgrens_heen(self, repo: HeffingenRepository):
        # 25 MWh niet-zakelijk: 20 MWh in schijf 1 (0-20) + 5 MWh in schijf 2 (20-50).
        bijzondere, energiebijdrage = repo.bereken_accijns_en_energiebijdrage(
            "elektriciteit", "niet_zakelijk", jaarverbruik_kwh=D("25000")
        )
        verwacht_bijzondere = D("20") * D("13.60") + D("5") * D("11.58")
        verwacht_energiebijdrage = D("25") * D("1.9261")
        assert bijzondere == verwacht_bijzondere
        assert energiebijdrage == verwacht_energiebijdrage

    def test_verbruik_exact_op_schijfgrens_telt_in_eerste_schijf(self, repo: HeffingenRepository):
        # 20 MWh exact: moet volledig tegen het 0-20-tarief berekend worden,
        # niet (deels) tegen het 20-50-tarief.
        bijzondere, energiebijdrage = repo.bereken_accijns_en_energiebijdrage(
            "elektriciteit", "niet_zakelijk", jaarverbruik_kwh=D("20000")
        )
        assert bijzondere == D("20") * D("13.60")
        assert energiebijdrage == D("20") * D("1.9261")

    def test_zakelijk_laagspanning_gebruikt_ander_tarief_dan_niet_zakelijk(
        self, repo: HeffingenRepository
    ):
        bijzondere, _ = repo.bereken_accijns_en_energiebijdrage(
            "elektriciteit", "zakelijk_laagspanning", jaarverbruik_kwh=D("5000")
        )
        assert bijzondere == D("5") * D("14.21")

    def test_zakelijk_hoogspanning_heeft_geen_energiebijdrage(self, repo: HeffingenRepository):
        _, energiebijdrage = repo.bereken_accijns_en_energiebijdrage(
            "elektriciteit", "zakelijk_hoogspanning", jaarverbruik_kwh=D("5000")
        )
        assert energiebijdrage == D("0")

    def test_onbekende_klantcategorie_faalt_hard(self, repo: HeffingenRepository):
        with pytest.raises(HeffingenError, match="onbekende_categorie"):
            repo.bereken_accijns_en_energiebijdrage(
                "elektriciteit", "onbekende_categorie", jaarverbruik_kwh=D("1000")
            )

    def test_onbekende_energievorm_faalt_hard(self, repo: HeffingenRepository):
        with pytest.raises(HeffingenError, match="aardgas"):
            repo.bereken_accijns_en_energiebijdrage(
                "aardgas", "niet_zakelijk", jaarverbruik_kwh=D("1000")
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
