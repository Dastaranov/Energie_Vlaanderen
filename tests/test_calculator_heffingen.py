"""Tests voor de heffingen-koppeling in Calculator.calculate() (Fase 2).

`grid_cost()` gebruikt een lege DNB-DataFrame zodat de nettarief-component
op 0 uitkomt — dat isoleert de heffingen-berekening, die hier het
daadwerkelijke onderwerp is. `DataRepository.dnb_for()`/`.dnb` bestaan
vandaag nog niet op de echte repository (die koppeling is een latere,
losstaande stap); deze fake volstaat om enkel `grid_cost()` bruikbaar te
maken voor deze test.
"""
from __future__ import annotations

from decimal import Decimal as D
from pathlib import Path

import pandas as pd
import pytest

from energie_vlaanderen.calculation.calculator import Calculator
from energie_vlaanderen.domain.models import Product, Profile
from energie_vlaanderen.heffingen.repository import HeffingenRepository

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config" / "heffingen"

DNB_COLUMNS = [
    "Netbeheerder", "Klanttype", "Contracttype",
    "Tariefdetail", "Tariefnotering", "Tarieftype", "Prijs_num",
]


class FakeGridRepository:
    """Levert een lege DNB-tabel: grid_cost() geeft dan altijd 0 terug."""

    def __init__(self) -> None:
        self.dnb = pd.DataFrame(columns=DNB_COLUMNS)

    def dnb_for(self, postcode, gemeente):
        return gemeente, "FA"


@pytest.fixture(scope="module")
def heffingen() -> HeffingenRepository:
    return HeffingenRepository.load(CONFIG_DIR)


def _product(segment: str, energy: str = "Elektriciteit") -> Product:
    return Product(
        2026, 6, segment, energy, "Afname", "X", "Y", "vast",
        {"day": D("20"), "night": D("15"), "fixed_fee": D("0"), "green": D("0"), "wkk": D("0")},
    )


def _profile(segment: str) -> Profile:
    # 2000 + 1000 kWh = 3 MWh/jaar — volledig binnen de eerste accijnsschijf
    # (0-20 MWh), zodat de verwachte bedragen met de hand na te rekenen zijn.
    return Profile("9280", "Lebbeke", segment, afname_dag_kwh=D("2000"), afname_nacht_kwh=D("1000"))


class TestLeviesPerKlantcategorie:
    def test_woning_levies_komt_overeen_met_handmatige_berekening(self, heffingen):
        calculator = Calculator(FakeGridRepository(), heffingen=heffingen)
        cost = calculator.calculate(_product("Woning"), _profile("Woning"))

        # 3 MWh niet_zakelijk: 3*13.60 bijzondere accijns + 3*1.9261
        # energiebijdrage + 0 (Energiefonds residentieel 2026 = 0,00 EUR/maand).
        verwacht = D("3") * D("13.60") + D("3") * D("1.9261") + D("0")
        assert cost.levies == verwacht
        assert cost.grid == D("0")

    def test_kmo_levies_komt_overeen_met_handmatige_berekening(self, heffingen):
        calculator = Calculator(FakeGridRepository(), heffingen=heffingen)
        cost = calculator.calculate(_product("Onderneming"), _profile("Onderneming"))

        # 3 MWh zakelijk_laagspanning: 3*14.21 bijzondere accijns +
        # 3*1.9261 energiebijdrage + 12*10.07 Energiefonds niet-residentieel 2026.
        verwacht = D("3") * D("14.21") + D("3") * D("1.9261") + D("12") * D("10.07")
        assert cost.levies == verwacht

    def test_kmo_levies_hoger_dan_woning_door_energiefonds(self, heffingen):
        calculator = Calculator(FakeGridRepository(), heffingen=heffingen)
        woning = calculator.calculate(_product("Woning"), _profile("Woning"))
        kmo = calculator.calculate(_product("Onderneming"), _profile("Onderneming"))

        assert kmo.levies > woning.levies
        # Het verschil wordt gedomineerd door het Energiefonds
        # (120,84 EUR/jaar), niet door het kleine accijnsverschil.
        assert (kmo.levies - woning.levies) > D("100")


class TestFoutafhandeling:
    def test_calculate_zonder_heffingen_repository_faalt(self):
        calculator = Calculator(FakeGridRepository())  # heffingen=None
        with pytest.raises(ValueError, match="HeffingenRepository"):
            calculator.calculate(_product("Woning"), _profile("Woning"))

    def test_calculate_voor_aardgas_faalt_nog(self, heffingen):
        calculator = Calculator(FakeGridRepository(), heffingen=heffingen)
        with pytest.raises(ValueError, match="aardgas|Gas"):
            calculator.calculate(_product("Woning", energy="Gas"), _profile("Woning"))
