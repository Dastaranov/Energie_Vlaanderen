"""De kern van `Calculator`: leverancierskost, formules en injectie.

De formuletak rekent een variabel product uit zijn eigen indexformule. Weigeren
zonder indexwaarde is hier het punt en niet de uitzondering: terugvallen op de
meegeleverde prijs zag er jarenlang goed uit terwijl 58 van de 61 variabele
producten hun formule nooit gebruikten.

De injectietak legt vast dat injectie op de *injectie*reeks gewaardeerd wordt.
Zonneproductie piekt wanneer de marktprijs laag staat; met de afnamereeks werd
dezelfde injectie twintig keer te hoog gewaardeerd.
"""
from decimal import Decimal as D

import pandas as pd
import pytest
from pathlib import Path


from energie_vlaanderen.calculation.calculator import Calculator
from experiments.remove.data_repository import DataRepository, DataRepositoryError
from energie_vlaanderen.domain.models import Product, Profile


pytestmark = pytest.mark.rekenen


def test_variable_formula():
    """De formulevorm zoals `DataRepository.products()` hem werkelijk oplevert.

    Deze test legde eerder een platte vorm vast (`{"A": ..., "name_A": ...}`)
    die door niets in dit project geproduceerd wordt: de repository schrijft
    `formula["index_A"] = {"name": ..., "value": ...}`. De test slaagde dus
    terwijl `formula_ct()` op de echte data nooit een indexwaarde vond en elk
    variabel product stil terugviel op de door VREG meegeleverde berekende
    prijs. Precies de foutklasse uit CLAUDE.md: groen, en toch verkeerd.

    Het getal: 0,11 x 85,31 + 1,51 = 10,8941 ct/kWh. De coëfficiënten en de
    indexwaarde komen uit de kolommen `a`/`z` en `index_value_A` van
    `master_var_dyn.csv` (`ingest/vtest/normalizer.py`).
    """
    formula = {
        "a": D("0.11"),
        "b": D("0"),
        "c": D("0"),
        "d": D("0"),
        "z": D("1.51"),
        "index_A": {"name": "x", "value": D("85.31")},
    }

    assert Calculator.heeft_indexwaarde(formula)
    assert Calculator.formula_ct(formula) == D("10.8941")


def test_variable_formula_zonder_indexwaarde_is_niet_doorrekenbaar():
    """Een formule met coëfficiënten maar zonder indexwaarde mag niet rekenen.

    Zonder deze controle zou `formula_ct()` alleen `z` teruggeven — een
    plausibel ogend getal dat de index volledig negeert. `supplier_cost()`
    gebruikt de uitkomst om bewust op de meegeleverde prijs terug te vallen,
    mét waarschuwing.
    """
    formula = {"a": D("0.11"), "z": D("1.51"), "index_A": {"name": "x", "value": None}}

    assert not Calculator.heeft_indexwaarde(formula)


def test_variable_formula_override_vervangt_de_indexwaarde():
    """Een override op naam vervangt de opgeslagen indexwaarde.

    De naam komt uit `index_name_A` in de brondata; dat is de sleutel waarop
    een actuelere marktwaarde ingevuld kan worden zonder de formule te wijzigen.
    """
    formula = {"a": D("0.11"), "z": D("1.51"), "index_A": {"name": "x", "value": D("85.31")}}

    assert Calculator.formula_ct(formula, {"x": D("100")}) == D("12.51")


def test_fixed_supplier():
    class EmptyRepository:
        pass

    calculator = Calculator(EmptyRepository())

    profile = Profile(
        "9280",
        "Lebbeke",
        afname_dag_kwh=D("2000"),
        afname_nacht_kwh=D("1000"),
    )

    product = Product(
        2026,
        6,
        "Woning",
        "Elektriciteit",
        "Afname",
        "X",
        "Y",
        "vast",
        {
            "day": D("20"),
            "night": D("15"),
            "fixed_fee": D("60"),
            "green": D("1"),
            "wkk": D("0.3"),
        },
    )

    cost, warnings = calculator.supplier_cost(
        product,
        profile,
    )

    assert cost == D("649")
    assert not warnings


def test_repository_reports_missing_data(tmp_path: Path):
    with pytest.raises(
        DataRepositoryError,
        match="Ontbrekende datasetbestanden",
    ):
        DataRepository(tmp_path)

class TestDynamischeInjectie:
    """Injectie en verbruik hebben tegengestelde dagprofielen.

    `Calculator.calculate()` gaf aan de injectie-tak de kwartierreeks van de
    *afname* mee. Bij een vast of variabel injectieproduct viel dat niet op —
    die gebruiken enkel de jaartotalen — maar de dynamische tak somt
    `volume_t x prijs_t` over de meegegeven reeks. Zonneproductie piekt rond de
    middag, wanneer de marktprijs juist laag staat; verbruik piekt 's avonds,
    wanneer ze hoog staat. De verkeerde reeks gebruiken overschat de
    injectieopbrengst dus systematisch.
    """

    @staticmethod
    def _markt():
        # Vier uren: goedkoop rond de middag, duur 's avonds. Zelfde vorm als
        # EntsoeMarketData.load(): timestamp (UTC) + price_eur_mwh.
        return pd.DataFrame(
            {
                "timestamp": pd.to_datetime(
                    ["2026-06-01T10:00Z", "2026-06-01T11:00Z",
                     "2026-06-01T18:00Z", "2026-06-01T19:00Z"],
                    utc=True,
                ),
                "price_eur_mwh": [10.0, 10.0, 200.0, 200.0],
            }
        )

    @staticmethod
    def _reeks(waarden):
        return pd.DataFrame(
            {
                "timestamp": pd.to_datetime(
                    ["2026-06-01T10:00Z", "2026-06-01T11:00Z",
                     "2026-06-01T18:00Z", "2026-06-01T19:00Z"],
                    utc=True,
                ),
                "afname_kwh": waarden,
            }
        )

    @staticmethod
    def _dynamisch(direction):
        # prijs_h = 1 x P_h + 0, in ct/kWh volgens de VNR-formulevorm.
        return Product(
            2026, 6, "Woning", "Elektriciteit", direction, "X", "Dyn", "dynamisch",
            {"fixed_fee": D("0"), "green": D("0"), "wkk": D("0")},
            {"dynamic": {"a": D("1"), "z": D("0")}},
        )

    def test_injectie_wordt_op_de_injectiereeks_gewaardeerd(self):
        """De middagzon telt tegen de middagprijs, niet tegen de avondprijs.

        4 kWh injectie, allemaal rond de middag bij 10 EUR/MWh: 4 x 10 x 1
        (a=1) = 40 ct = 0,40 EUR. Wie de verbruiksreeks zou gebruiken — 4 kWh
        's avonds bij 200 EUR/MWh — komt op 8,00 EUR, twintig keer zoveel.
        """
        calculator = Calculator(EmptyGridRepository(), heffingen=NulHeffingen())
        profiel = Profile(
            "9280", "Lebbeke",
            afname_dag_kwh=D("4"), injectie_dag_kwh=D("4"),
        )
        kost = calculator.calculate(
            self._dynamisch("Afname"),
            profiel,
            market=self._markt(),
            intervals=self._reeks([0.0, 0.0, 2.0, 2.0]),      # 's avonds verbruikt
            inject_product=self._dynamisch("Injectie"),
            injectie_intervals=self._reeks([2.0, 2.0, 0.0, 0.0]),  # 's middags geinjecteerd
        )
        assert kost.injection_credit == D("0.40")
        # Het verbruik staat wél op de dure uren: 4 x 200 x 1 / 100 = 8,00 EUR.
        assert kost.supplier == D("8.00")

    def test_zonder_injectiereeks_stopt_een_dynamisch_injectieproduct(self):
        """Een vlak profiel is voor injectie geen benadering maar onzin.

        Zonneproductie is 's nachts nul. Het jaarvolume gelijkmatig over alle
        kwartieren spreiden waardeert die kWh tegen het daggemiddelde en
        overschat de opbrengst structureel — liever stoppen.
        """
        calculator = Calculator(EmptyGridRepository(), heffingen=NulHeffingen())
        profiel = Profile("9280", "Lebbeke", afname_dag_kwh=D("4"), injectie_dag_kwh=D("4"))
        with pytest.raises(ValueError, match="vlak profiel"):
            calculator.calculate(
                self._dynamisch("Afname"),
                profiel,
                market=self._markt(),
                intervals=self._reeks([0.0, 0.0, 2.0, 2.0]),
                inject_product=self._dynamisch("Injectie"),
                injectie_intervals=None,
            )


class EmptyGridRepository:
    """Minimale DNB-tabel met alle tarieven expliciet op 0.

    Zelfde reden als `FakeGridRepository` in `test_calculator_heffingen.py`: een
    lege tabel is sinds kort een fout, want een ontbrekend nettarief mag geen
    stille 0 worden. Rijen mét waarde 0 zijn dat wél, en isoleren hier de
    leverancierskost en het injectiekrediet.
    """

    _KOLOMMEN = ["Netbeheerder", "Klanttype", "Contracttype", "Tarieftype",
                 "Tariefdetail", "Tariefnotering", "Prijs_num"]
    _RIJEN = [
        ("FA", "ELEK_LS_DIGI", "Afname", "Tarieven voor het netgebruik",
         "Gemiddelde maandpiek", "EUR/kW/jaar", 0.0),
        ("FA", "ELEK_LS_DIGI", "Afname", "Tarieven voor het netgebruik",
         "kWh-tarief", "EUR/kWh", 0.0),
    ]

    def __init__(self):
        self.dnb = pd.DataFrame(
            [dict(zip(self._KOLOMMEN, rij)) for rij in self._RIJEN],
            columns=self._KOLOMMEN,
        )

    def dnb_for(self, postcode, gemeente, energie_type="elektriciteit"):
        return gemeente, "FA"


class NulHeffingen:
    """Heffingen op nul, zodat alleen de leverancierskost en het krediet tellen."""

    def bereken_accijns_en_energiebijdrage(self, *args, **kwargs):
        return D("0"), D("0")

    def energiefonds_per_jaar(self, *args, **kwargs):
        return D("0")
