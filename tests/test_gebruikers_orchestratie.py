"""Tests voor `gebruikers.orchestratie` die geen databank nodig hebben.

`bereken_dossier()` zelf (de databankopzet, de lus over aansluitingspunten)
kan alleen end-to-end tegen een echte databank getoetst worden — dat gebeurt
via `gebruiker bereken` zelf (`tests/test_cli.py`,
`tests/test_berekening_leest_geen_pipeline_csv.py`, beide `integration`). Wat
hier zonder databank getoetst wordt: `DossierResultaat`'s eigen rekenwerk
(`totalen`, `exactheidsklasse`) en `laad_metingen()`/`laad_markt()`, die op een
dossier resp. instellingen werken zonder verbinding te openen.
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
from energie_vlaanderen.gebruikers.orchestratie import DossierResultaat, laad_markt, laad_metingen
from energie_vlaanderen.gebruikers.periodes import Deelperiode
from energie_vlaanderen.gebruikers.toml_io import Dossier
from energie_vlaanderen.settings import Settings

pytestmark = pytest.mark.dossier


def _berekening(supplier: D, exactheidsklasse=Exactheidsklasse.EXACT) -> Berekening:
    periode = Deelperiode(date(2026, 1, 1), date(2027, 1, 1), None)
    product = Product(
        year=2026, month=1, segment="Woning", energy="elektriciteit",
        direction="afname", supplier="Test", name="Test", kind="vast",
    )
    kost = Cost(supplier=supplier, grid=D("10"))
    regel = PeriodeResultaat(
        periode=periode, kost=kost, product=product, exactheidsklasse=exactheidsklasse,
    )
    return Berekening(
        van=periode.van, tot=periode.tot, regels=(regel,), exactheidsklasse=exactheidsklasse,
    )


def test_totalen_som_over_alle_aansluitingspunten():
    elek = Aansluitingspunt(Gebruiker().id, EnergieType.ELEKTRICITEIT, "9300", "Aalst")
    gas = Aansluitingspunt(Gebruiker().id, EnergieType.GAS, "9300", "Aalst")
    uitslag = DossierResultaat(
        resultaten=((elek, _berekening(D("100"))), (gas, _berekening(D("50")))),
        mislukt=(), dataversie="test", nettarieven_jaren=(2026,),
        metingen=None, meetreeks=None, meetwaarschuwingen=(), markt=None,
    )
    assert uitslag.totalen["supplier"] == D("150")
    assert uitslag.totalen["grid"] == D("20")


def test_totalen_is_leeg_zonder_resultaten():
    uitslag = DossierResultaat(
        resultaten=(), mislukt=(("gas", "geen contract"),), dataversie=None,
        nettarieven_jaren=(), metingen=None, meetreeks=None,
        meetwaarschuwingen=(), markt=None,
    )
    assert uitslag.totalen == {}


def test_exactheidsklasse_is_de_zwakste_van_de_punten():
    elek = Aansluitingspunt(Gebruiker().id, EnergieType.ELEKTRICITEIT, "9300", "Aalst")
    gas = Aansluitingspunt(Gebruiker().id, EnergieType.GAS, "9300", "Aalst")
    uitslag = DossierResultaat(
        resultaten=(
            (elek, _berekening(D("100"), Exactheidsklasse.EXACT)),
            (gas, _berekening(D("50"), Exactheidsklasse.GESCHAT)),
        ),
        mislukt=(), dataversie="test", nettarieven_jaren=(2026,),
        metingen=None, meetreeks=None, meetwaarschuwingen=(), markt=None,
    )
    assert uitslag.exactheidsklasse is Exactheidsklasse.GESCHAT


def test_laad_metingen_zonder_fluvius_csv_geeft_niets():
    dossier = Dossier(
        bron=None, gebruiker=Gebruiker(), persoonsgegevens=None,
        aansluitingspunten=(), meters=(), assets=(), contracten=(),
        verbruiksopgaven=(), fluvius_csv=None,
    )
    meetreeks, waarschuwingen = laad_metingen(dossier)
    assert meetreeks is None
    assert waarschuwingen == ()


def test_laad_markt_zonder_cache_geeft_niets(tmp_path):
    settings = Settings(project_root=tmp_path, data_root=tmp_path / "data")
    resultaat = laad_markt(settings, date(2026, 1, 1), date(2026, 2, 1))
    assert resultaat is None
