"""Tests voor de heffingen-koppeling in Calculator.calculate() (Fase 2).

`grid_cost()` gebruikt een lege DNB-DataFrame zodat de nettarief-component
op 0 uitkomt — dat isoleert de heffingen-berekening, die hier het
daadwerkelijke onderwerp is. `DataRepository.dnb_for()`/`.dnb` bestaan
vandaag nog niet op de echte repository (die koppeling is een latere,
losstaande stap); deze fake volstaat om enkel `grid_cost()` bruikbaar te
maken voor deze test.
"""
from __future__ import annotations

from decimal import Decimal
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

        # Product uit juni 2026, dus het regime van 01/07/2023: 3 MWh
        # niet_zakelijk tegen 47,4811 EUR/MWh, geen energiebijdrage voor
        # huishoudens, en Energiefonds residentieel 2026 = 0,00 EUR/maand.
        verwacht = D("3") * D("47.4811") + D("0") + D("0")
        assert cost.levies == verwacht
        assert cost.grid == D("0")

    def test_kmo_levies_komt_overeen_met_handmatige_berekening(self, heffingen):
        calculator = Calculator(FakeGridRepository(), heffingen=heffingen)
        cost = calculator.calculate(_product("Onderneming"), _profile("Onderneming"))

        # 3 MWh zakelijk_laagspanning: 3*14,21 bijzondere accijns +
        # 3*1,9261 energiebijdrage + 12*10,07 Energiefonds niet-residentieel
        # 2026. De hervorming van 2023 gold enkel voor gezinnen, dus
        # ondernemingen staan nog op de tarieven van de programmawet 2021 —
        # bevestigd op vtest.be (15.000 kWh -> 213,15 EUR = 14,21 EUR/MWh).
        verwacht = D("3") * D("14.21") + D("3") * D("1.9261") + D("12") * D("10.07")
        assert cost.levies == verwacht

    def test_kmo_en_woning_wisselen_van_plaats_bij_hoger_verbruik(self, heffingen):
        """Twee tegengestelde effecten kruisen elkaar rond 3,9 MWh.

        De onderneming betaalt een vast Energiefonds van 120,84 EUR/jaar dat
        het gezin niet betaalt, maar een veel lagere accijns (14,21 tegenover
        47,4811 EUR/MWh). Bij een klein verbruik weegt het Energiefonds
        zwaarder, daarboven de accijns.
        """
        calculator = Calculator(FakeGridRepository(), heffingen=heffingen)

        def levies(segment: str, kwh: str) -> Decimal:
            profiel = Profile(
                "9280", "Lebbeke", segment, afname_dag_kwh=D(kwh)
            )
            return calculator.calculate(_product(segment), profiel).levies

        assert levies("Onderneming", "3000") > levies("Woning", "3000")
        assert levies("Onderneming", "10000") < levies("Woning", "10000")


class TestFoutafhandeling:
    def test_calculate_zonder_heffingen_repository_faalt(self):
        calculator = Calculator(FakeGridRepository())  # heffingen=None
        with pytest.raises(ValueError, match="HeffingenRepository"):
            calculator.calculate(_product("Woning"), _profile("Woning"))

    def test_calculate_voor_aardgas_faalt_nog(self, heffingen):
        calculator = Calculator(FakeGridRepository(), heffingen=heffingen)
        with pytest.raises(ValueError, match="aardgas|Gas"):
            calculator.calculate(_product("Woning", energy="Gas"), _profile("Woning"))


class TestTariefwissel:
    """De bijzondere accijns daalde op 01/08/2026 van 47,4811 naar 46,00
    EUR/MWh. De Calculator moet de maand van het product volgen, niet het
    jaar — anders krijgt een factuur van augustus het julitarief."""

    def test_juli_en_augustus_2026_verschillen(self, heffingen):
        calculator = Calculator(FakeGridRepository(), heffingen=heffingen)
        juli = Product(
            2026, 7, "Woning", "Elektriciteit", "Afname", "X", "Y", "vast",
            {"day": D("20"), "night": D("15"), "fixed_fee": D("0"),
             "green": D("0"), "wkk": D("0")},
        )
        augustus = Product(
            2026, 8, "Woning", "Elektriciteit", "Afname", "X", "Y", "vast",
            {"day": D("20"), "night": D("15"), "fixed_fee": D("0"),
             "green": D("0"), "wkk": D("0")},
        )
        profiel = _profile("Woning")

        kost_juli = calculator.calculate(juli, profiel)
        kost_augustus = calculator.calculate(augustus, profiel)

        assert kost_juli.levies == D("3") * D("47.4811")
        assert kost_augustus.levies == D("3") * D("46.0000")
