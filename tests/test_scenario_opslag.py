"""Tests voor `scenario.opslag`: JSON/YAML-opslag van een `ScenarioResultaat`.

Het doel is hergebruik van de cijfers (een webinterface, een los script), niet
een identieke Python-round-trip — zie de moduledocstring van `opslag.py`. Wat
hier getoetst wordt: geen `Decimal`/datum/enum die de JSON-/YAML-encoder doet
struikelen, en dat beide formaten dezelfde cijfers dragen.
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal as D

import pytest

from energie_vlaanderen.domain.models import Cost
from energie_vlaanderen.gebruikers.berekening import Berekening, PeriodeResultaat
from energie_vlaanderen.gebruikers.models import Aanname, EnergieType, Exactheidsklasse
from energie_vlaanderen.gebruikers.periodes import Deelperiode
from energie_vlaanderen.scenario import opslag
from energie_vlaanderen.scenario.basis import ScenarioResultaat

pytestmark = pytest.mark.dossier


def _berekening() -> Berekening:
    from energie_vlaanderen.domain.models import Product

    periode = Deelperiode(date(2026, 1, 1), date(2027, 1, 1), None)
    product = Product(
        year=2026, month=1, segment="Woning", energy="elektriciteit",
        direction="afname", supplier="Bolt", name="Bolt Variabel", kind="variabel",
    )
    kost = Cost(supplier=D("300.5"), grid=D("100"), levies=D("50"), vat=D("20"))
    regel = PeriodeResultaat(
        periode=periode, kost=kost, product=product,
        exactheidsklasse=Exactheidsklasse.EXACT,
    )
    return Berekening(
        van=periode.van, tot=periode.tot, regels=(regel,),
        exactheidsklasse=Exactheidsklasse.EXACT,
        aannames=(Aanname(veld="maandpiek_kw", waarde="4.218", bron="vtest.be", geverifieerd=True),),
    )


@pytest.fixture
def resultaat() -> ScenarioResultaat:
    return ScenarioResultaat(
        naam="Test-scenario",
        omschrijving="Een testscenario",
        basislijn={EnergieType.ELEKTRICITEIT: _berekening()},
        scenario={EnergieType.ELEKTRICITEIT: _berekening()},
        verschil_eur={"elektriciteit": D("-50.25"), "totaal": D("-50.25")},
        exactheidsklasse=Exactheidsklasse.SCENARIO,
    )


def test_naar_dict_bevat_geen_decimal_of_datumobjecten(resultaat):
    """`json.dumps` zonder `default=` moet slagen — dat bewijst dat er geen
    `Decimal`/`date`/enum meer in het dict zit, enkel `str`/`int`/`bool`/`None`."""
    inhoud = opslag.naar_dict(resultaat)
    json.dumps(inhoud)  # gooit TypeError als er nog een niet-JSON-type in zit


def test_json_round_trip(tmp_path, resultaat):
    pad = opslag.sla_op(resultaat, tmp_path / "scenario.json", formaat="json")
    teruggelezen = opslag.laad(pad)

    assert teruggelezen["naam"] == "Test-scenario"
    assert teruggelezen["verschil_eur"]["totaal"] == "-50.25"
    assert teruggelezen["scenario"]["elektriciteit"]["totalen"]["supplier"] == "300.50"


def test_yaml_round_trip(tmp_path, resultaat):
    pad = opslag.sla_op(resultaat, tmp_path / "scenario.yaml", formaat="yaml")
    teruggelezen = opslag.laad(pad)

    assert teruggelezen["naam"] == "Test-scenario"
    assert teruggelezen["verschil_eur"]["totaal"] == "-50.25"


def test_json_en_yaml_dragen_dezelfde_cijfers(tmp_path, resultaat):
    json_pad = opslag.sla_op(resultaat, tmp_path / "a.json", formaat="json")
    yaml_pad = opslag.sla_op(resultaat, tmp_path / "a.yaml", formaat="yaml")

    assert opslag.laad(json_pad) == opslag.laad(yaml_pad)


def test_onbekend_formaat_wordt_geweigerd(tmp_path, resultaat):
    with pytest.raises(ValueError, match="Onbekend formaat"):
        opslag.sla_op(resultaat, tmp_path / "x.txt", formaat="txt")  # type: ignore[arg-type]


def test_map_wordt_aangemaakt_indien_nodig(tmp_path, resultaat):
    pad = tmp_path / "nog" / "niet" / "bestaand" / "scenario.json"
    opslag.sla_op(resultaat, pad)
    assert pad.is_file()
