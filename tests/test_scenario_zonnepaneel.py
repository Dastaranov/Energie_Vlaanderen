"""Tests voor `scenario.zonnepaneel.ZonnepaneelScenario.pas_toe()`.

Zelfde scope-afbakening als `test_scenario_batterij.py`: `voer_uit()` zelf
heeft een databank nodig (SPP-profiel, `Kostberekening`); hier wordt enkel de
dossiersurgerie getoetst.
"""
from __future__ import annotations

from decimal import Decimal as D

import pytest

from energie_vlaanderen.gebruikers.models import (
    Aansluitingspunt,
    AssetType,
    EnergieType,
    Gebruiker,
)
from energie_vlaanderen.gebruikers.toml_io import Dossier
from energie_vlaanderen.scenario.zonnepaneel import ZonnepaneelScenario

pytestmark = pytest.mark.dossier


def _dossier(punt: Aansluitingspunt) -> Dossier:
    return Dossier(
        bron=None, gebruiker=Gebruiker(), persoonsgegevens=None,
        aansluitingspunten=(punt,), meters=(), assets=(),
        contracten=(), verbruiksopgaven=(),
    )


def test_voegt_een_pv_asset_toe_met_het_gevraagde_vermogen():
    punt = Aansluitingspunt(Gebruiker().id, EnergieType.ELEKTRICITEIT, "9300", "Aalst")
    dossier = _dossier(punt)
    scenario = ZonnepaneelScenario(kwp=D("6.5"), merk="JA Solar", model="JAM54S30-440")

    gewijzigd = scenario.pas_toe(dossier)

    (asset,) = gewijzigd.assets
    assert asset.type is AssetType.PV
    assert asset.kwp == D("6.5")
    assert asset.merk == "JA Solar"


def test_muteert_het_origineel_niet():
    punt = Aansluitingspunt(Gebruiker().id, EnergieType.ELEKTRICITEIT, "9300", "Aalst")
    dossier = _dossier(punt)
    scenario = ZonnepaneelScenario(kwp=D("6.5"))

    scenario.pas_toe(dossier)

    assert dossier.assets == ()


def test_weigert_zonder_elektriciteitsaansluiting():
    punt = Aansluitingspunt(Gebruiker().id, EnergieType.GAS, "9300", "Aalst")
    dossier = _dossier(punt)
    scenario = ZonnepaneelScenario(kwp=D("6.5"))

    with pytest.raises(ValueError, match="geen elektriciteitsaansluiting"):
        scenario.pas_toe(dossier)


def test_naam_wordt_automatisch_ingevuld():
    scenario = ZonnepaneelScenario(kwp=D("6.5"))
    assert "6.5" in scenario.naam
