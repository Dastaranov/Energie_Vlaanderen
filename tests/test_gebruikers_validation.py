"""Tests voor `gebruikers.validation.controleer_dossier()`.

Enkel het nieuwe gedrag voor `AssetType.GASTOESTEL` — er bestond nog geen
testbestand voor deze module. Een gastoestel zonder `vermogen_kw`/`doel`
telt vandaag niet mee in de berekening (het gasverbruik komt uit
`[[verbruiksopgave]]`), maar de ontbrekende data mag niet stil onopgemerkt
blijven: ze is nodig zodra een warmtevraagmodel het toestel wél gebruikt.
"""
from __future__ import annotations

from decimal import Decimal as D

import pytest

from energie_vlaanderen.gebruikers.models import (
    AssetType,
    Gebruiker,
    InstallatieAsset,
)
from energie_vlaanderen.gebruikers.toml_io import Dossier
from energie_vlaanderen.gebruikers.validation import controleer_dossier
from energie_vlaanderen.hardware.repository import BatterijRepository, OmvormerRepository

pytestmark = pytest.mark.dossier


def _dossier(*, assets=()) -> Dossier:
    gebruiker = Gebruiker()
    return Dossier(
        bron=None, gebruiker=gebruiker, persoonsgegevens=None,
        aansluitingspunten=(), meters=(), assets=assets,
        contracten=(), verbruiksopgaven=(),
    )


def _hardware():
    return BatterijRepository({}), OmvormerRepository({})


def test_gastoestel_zonder_vermogen_geeft_een_waarschuwing():
    asset = InstallatieAsset(
        aansluitingspunt_id=Gebruiker().id, type=AssetType.GASTOESTEL,
        model="ketel", doel="beide",
    )
    bevindingen = controleer_dossier(_dossier(assets=(asset,)), hardware=_hardware())

    waarschuwingen = [b for b in bevindingen if b.onderwerp == "installatie/gastoestel"]
    assert any("vermogen_kw" in b.bericht for b in waarschuwingen)


def test_gastoestel_zonder_doel_geeft_een_waarschuwing():
    asset = InstallatieAsset(
        aansluitingspunt_id=Gebruiker().id, type=AssetType.GASTOESTEL,
        model="kachel", vermogen_kw=D("6"),
    )
    bevindingen = controleer_dossier(_dossier(assets=(asset,)), hardware=_hardware())

    waarschuwingen = [b for b in bevindingen if b.onderwerp == "installatie/gastoestel"]
    assert any("doel" in b.bericht for b in waarschuwingen)


def test_volledig_gastoestel_geeft_geen_waarschuwing():
    asset = InstallatieAsset(
        aansluitingspunt_id=Gebruiker().id, type=AssetType.GASTOESTEL,
        model="ketel", vermogen_kw=D("25"), doel="beide",
    )
    bevindingen = controleer_dossier(_dossier(assets=(asset,)), hardware=_hardware())

    assert not [b for b in bevindingen if b.onderwerp == "installatie/gastoestel"]


def test_zonder_hardware_wordt_er_niets_over_gastoestellen_gezegd():
    """`hardware=None` (de standaard) slaat `_controleer_hardware()` helemaal
    over — geen valse verwachting dat een gastoestel zonder databankverbinding
    toch getoetst wordt."""
    asset = InstallatieAsset(
        aansluitingspunt_id=Gebruiker().id, type=AssetType.GASTOESTEL, model="ketel",
    )
    bevindingen = controleer_dossier(_dossier(assets=(asset,)))

    assert not [b for b in bevindingen if b.onderwerp == "installatie/gastoestel"]
