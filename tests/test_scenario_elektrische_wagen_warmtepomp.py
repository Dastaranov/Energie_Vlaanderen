"""Tests voor `pas_toe()` van `ElektrischeWagenScenario`/`WarmtepompScenario`.

Zelfde scope-afbakening als de andere `scenario.*`-tests: `voer_uit()` zelf
heeft een databank nodig; hier wordt enkel de dossiersurgerie getoetst
(asset toevoegen, en bij `WarmtepompScenario` het optioneel wegvegen van het
gasverbruik).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from energie_vlaanderen.gebruikers.models import (
    Aansluitingspunt,
    AssetType,
    EnergieType,
    Gebruiker,
    Verbruiksopgave,
)
from energie_vlaanderen.gebruikers.toml_io import Dossier
from energie_vlaanderen.scenario.elektrische_wagen import ElektrischeWagenScenario
from energie_vlaanderen.scenario.warmtepomp import WarmtepompScenario

pytestmark = pytest.mark.dossier


def _dossier(*aansluitingspunten, verbruiksopgaven=()) -> Dossier:
    return Dossier(
        bron=None, gebruiker=Gebruiker(), persoonsgegevens=None,
        aansluitingspunten=aansluitingspunten, meters=(), assets=(),
        contracten=(), verbruiksopgaven=verbruiksopgaven,
    )


class TestElektrischeWagenScenario:
    def test_voegt_een_ev_asset_toe(self):
        punt = Aansluitingspunt(Gebruiker().id, EnergieType.ELEKTRICITEIT, "9300", "Aalst")
        dossier = _dossier(punt)
        scenario = ElektrischeWagenScenario(merk="Volkswagen", model="ID.3 Pro", km_per_jaar=D("15000"))

        gewijzigd = scenario.pas_toe(dossier)

        (asset,) = gewijzigd.assets
        assert asset.type is AssetType.EV
        assert asset.merk == "Volkswagen"

    def test_muteert_het_origineel_niet(self):
        punt = Aansluitingspunt(Gebruiker().id, EnergieType.ELEKTRICITEIT, "9300", "Aalst")
        dossier = _dossier(punt)
        scenario = ElektrischeWagenScenario(merk="Volkswagen", model="ID.3 Pro", km_per_jaar=D("15000"))

        scenario.pas_toe(dossier)

        assert dossier.assets == ()

    def test_weigert_zonder_elektriciteitsaansluiting(self):
        punt = Aansluitingspunt(Gebruiker().id, EnergieType.GAS, "9300", "Aalst")
        dossier = _dossier(punt)
        scenario = ElektrischeWagenScenario(merk="Volkswagen", model="ID.3 Pro", km_per_jaar=D("15000"))

        with pytest.raises(ValueError, match="geen elektriciteitsaansluiting"):
            scenario.pas_toe(dossier)


class TestWarmtepompScenario:
    def test_voegt_een_warmtepomp_asset_toe(self):
        punt = Aansluitingspunt(Gebruiker().id, EnergieType.ELEKTRICITEIT, "9300", "Aalst")
        dossier = _dossier(punt)
        scenario = WarmtepompScenario(merk="Daikin", model="Altherma 3 H HT", warmtevraag_kwh_jaar=D("15000"))

        gewijzigd = scenario.pas_toe(dossier)

        (asset,) = gewijzigd.assets
        assert asset.type is AssetType.WARMTEPOMP

    def test_vervangt_gas_zet_het_gasverbruik_op_nul(self):
        elek = Aansluitingspunt(Gebruiker().id, EnergieType.ELEKTRICITEIT, "9300", "Aalst")
        gas = Aansluitingspunt(Gebruiker().id, EnergieType.GAS, "9300", "Aalst")
        opgave = Verbruiksopgave(
            gas.id, date(2026, 1, 1), date(2027, 1, 1), afname_dag_kwh=D("15000"),
        )
        dossier = _dossier(elek, gas, verbruiksopgaven=(opgave,))
        scenario = WarmtepompScenario(
            merk="Daikin", model="Altherma 3 H HT", warmtevraag_kwh_jaar=D("15000"),
            vervangt_gas=True,
        )

        gewijzigd = scenario.pas_toe(dossier)

        (aangepaste_opgave,) = gewijzigd.opgaven_van(gas)
        assert aangepaste_opgave.afname_kwh == D("0")

    def test_zonder_vervangt_gas_blijft_het_gasverbruik_ongemoeid(self):
        elek = Aansluitingspunt(Gebruiker().id, EnergieType.ELEKTRICITEIT, "9300", "Aalst")
        gas = Aansluitingspunt(Gebruiker().id, EnergieType.GAS, "9300", "Aalst")
        opgave = Verbruiksopgave(
            gas.id, date(2026, 1, 1), date(2027, 1, 1), afname_dag_kwh=D("15000"),
        )
        dossier = _dossier(elek, gas, verbruiksopgaven=(opgave,))
        scenario = WarmtepompScenario(
            merk="Daikin", model="Altherma 3 H HT", warmtevraag_kwh_jaar=D("15000"),
        )

        gewijzigd = scenario.pas_toe(dossier)

        (ongemoeide_opgave,) = gewijzigd.opgaven_van(gas)
        assert ongemoeide_opgave.afname_kwh == D("15000")

    def test_muteert_het_origineel_niet(self):
        elek = Aansluitingspunt(Gebruiker().id, EnergieType.ELEKTRICITEIT, "9300", "Aalst")
        gas = Aansluitingspunt(Gebruiker().id, EnergieType.GAS, "9300", "Aalst")
        opgave = Verbruiksopgave(
            gas.id, date(2026, 1, 1), date(2027, 1, 1), afname_dag_kwh=D("15000"),
        )
        dossier = _dossier(elek, gas, verbruiksopgaven=(opgave,))
        scenario = WarmtepompScenario(
            merk="Daikin", model="Altherma 3 H HT", warmtevraag_kwh_jaar=D("15000"),
            vervangt_gas=True,
        )

        scenario.pas_toe(dossier)

        assert dossier.opgaven_van(gas)[0].afname_kwh == D("15000")
