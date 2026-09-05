"""Tests voor `scenario.basis.Scenario`/`ScenarioResultaat`: de generieke diff.

Geen databank nodig — `Scenario._verpak()` werkt op reeds berekende
`DossierResultaat`s, dus die worden hier met de hand opgebouwd (dezelfde
domeinobjecten als `test_gebruikers_berekening.py` gebruikt, alleen zonder de
echte tariefopzoeking).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from energie_vlaanderen.domain.models import Cost, Product
from energie_vlaanderen.gebruikers.berekening import Berekening, PeriodeResultaat
from energie_vlaanderen.gebruikers.models import (
    Aansluitingspunt,
    EnergieType,
    Exactheidsklasse,
    Gebruiker,
)
from energie_vlaanderen.gebruikers.orchestratie import DossierResultaat
from energie_vlaanderen.gebruikers.periodes import Deelperiode
from energie_vlaanderen.scenario.basis import Scenario

pytestmark = pytest.mark.dossier


def _product(naam: str) -> Product:
    return Product(
        year=2026, month=1, segment="Woning", energy="elektriciteit",
        direction="afname", supplier="Test", name=naam, kind="vast",
    )


def _berekening(totaal_supplier: D, *, exactheidsklasse=Exactheidsklasse.EXACT) -> Berekening:
    periode = Deelperiode(date(2026, 1, 1), date(2027, 1, 1), None)
    kost = Cost(supplier=totaal_supplier, grid=D("100"), levies=D("50"), vat=D("20"))
    regel = PeriodeResultaat(
        periode=periode, kost=kost, product=_product("Test"),
        exactheidsklasse=exactheidsklasse,
    )
    return Berekening(
        van=periode.van, tot=periode.tot, regels=(regel,),
        exactheidsklasse=exactheidsklasse,
    )


def _dossierresultaat(
    punt: Aansluitingspunt, berekening: Berekening, *, mislukt=(),
) -> DossierResultaat:
    return DossierResultaat(
        resultaten=((punt, berekening),), mislukt=mislukt, dataversie="test",
        nettarieven_jaren=(2026,), metingen=None, meetreeks=None,
        meetwaarschuwingen=(), markt=None,
    )


class _VasteWijziging(Scenario):
    """Testdouble: `pas_toe()` doet niets — enkel de diffmachinerie wordt getoetst."""

    naam = "Test"
    omschrijving = "Test"

    def pas_toe(self, dossier):
        return dossier


def test_verschil_is_scenario_min_basislijn():
    punt = Aansluitingspunt(Gebruiker().id, EnergieType.ELEKTRICITEIT, "9300", "Aalst")
    basislijn = _dossierresultaat(punt, _berekening(D("300")))
    scenario_resultaat = _dossierresultaat(punt, _berekening(D("250")))

    resultaat = _VasteWijziging()._verpak(basislijn, scenario_resultaat)

    # 300 supplier + 100 grid + 50 levies + 20 vat = 470 basislijn
    # 250 supplier + 100 grid + 50 levies + 20 vat = 420 scenario
    assert resultaat.totaal_basislijn == D("470")
    assert resultaat.totaal_scenario == D("420")
    assert resultaat.verschil_eur[str(EnergieType.ELEKTRICITEIT)] == D("-50")
    assert resultaat.verschil_eur["totaal"] == D("-50")


def test_exactheidsklasse_is_nooit_beter_dan_scenario():
    """Ook als beide onderliggende berekeningen `exact` zijn, is het resultaat
    `scenario` — Manifest §5.8: een scenario is per definitie hypothetisch."""
    punt = Aansluitingspunt(Gebruiker().id, EnergieType.ELEKTRICITEIT, "9300", "Aalst")
    basislijn = _dossierresultaat(punt, _berekening(D("300"), exactheidsklasse=Exactheidsklasse.EXACT))
    scenario_resultaat = _dossierresultaat(punt, _berekening(D("250"), exactheidsklasse=Exactheidsklasse.EXACT))

    resultaat = _VasteWijziging()._verpak(basislijn, scenario_resultaat)

    assert resultaat.exactheidsklasse is Exactheidsklasse.SCENARIO


def test_een_mislukt_punt_in_het_scenario_wordt_gemeld():
    """Regressietest: een puntsoort die in het scenario wegvalt (bv. door een
    fout in de gewijzigde contracthistoriek) maakte het verschil eerder stil
    onvolledig — de som liep dan over minder punten dan de basislijn, zonder
    dat iets dat zei. Zie CLAUDE.md "Een fout op het ene punt laat het andere
    niet vervallen": het punt mag ontbreken, de melding niet."""
    punt = Aansluitingspunt(Gebruiker().id, EnergieType.ELEKTRICITEIT, "9300", "Aalst")
    basislijn = _dossierresultaat(punt, _berekening(D("300")))
    scenario_resultaat = _dossierresultaat(
        punt, _berekening(D("250")),
        mislukt=(("gas", "Geen leveringscontract voor deze periode."),),
    )

    resultaat = _VasteWijziging()._verpak(basislijn, scenario_resultaat)

    assert any("gas" in w and "niet doorgerekend" in w for w in resultaat.warnings)


def test_exactheidsklasse_volgt_de_zwakste_component():
    """Een geschatte basislijn maakt het scenario niet `scenario`-plus-nog-iets
    — `SCENARIO` weegt al zwaarder dan `GESCHAT`, dus die blijft de uitkomst."""
    punt = Aansluitingspunt(Gebruiker().id, EnergieType.ELEKTRICITEIT, "9300", "Aalst")
    basislijn = _dossierresultaat(punt, _berekening(D("300"), exactheidsklasse=Exactheidsklasse.GESCHAT))
    scenario_resultaat = _dossierresultaat(punt, _berekening(D("250"), exactheidsklasse=Exactheidsklasse.EXACT))

    resultaat = _VasteWijziging()._verpak(basislijn, scenario_resultaat)

    assert resultaat.exactheidsklasse is Exactheidsklasse.SCENARIO
