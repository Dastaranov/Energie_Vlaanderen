"""Tests voor de structurele controle op config/hardware/ (hardware/validation.py).

Zelfde regels als bij heffingen/nettarieven: `geverifieerd = true` zonder
bronvermelding is een fout, `geverifieerd = false` is een waarschuwing (nooit
een fout — elk model start ongeverifieerd).
"""
from __future__ import annotations

import pytest

from energie_vlaanderen.hardware.models import BatterijSpec, OmvormerSpec
from energie_vlaanderen.hardware.repository import BatterijRepository, OmvormerRepository
from energie_vlaanderen.hardware.validation import (
    controleer_batterijen,
    controleer_omvormers,
)


pytestmark = pytest.mark.masterdata


def _batterijspec(**overrides) -> BatterijSpec:
    basis = dict(
        merk="Test",
        model="Model",
        synergrid_id="",
        power_control_system="Hybride",
        p_active_power_w=1000.0,
        smax_apparent_power_w=1000.0,
        num_phase=1,
        max_charge_w=1000.0,
        max_discharge_w=1000.0,
        max_capacity_kwh=1.0,
        minimum_capacity_pct=10.0,
        standby_power_w=5.0,
        round_trip_efficiency_pct=95.0,
        rte_ac_dc_pct=98.0,
        rte_dc_ac_pct=98.0,
        rte_storage_pct=99.0,
        ramp_up_time_s=0.5,
        max_cycle=6000,
        max_depth_of_discharge_pct=90.0,
        c_rate=0.5,
        eol_criteria_pct=80.0,
        geverifieerd=False,
        bron="",
        datasheet_versie="",
        datasheet_datum="",
        opgehaald_op="",
    )
    basis.update(overrides)
    return BatterijSpec(**basis)


def _omvormerspec(**overrides) -> OmvormerSpec:
    basis = dict(
        merk="Test",
        model="Model",
        product_type="hybride",
        nominaal_ac_vermogen_w=5000.0,
        max_ac_vermogen_w=5000.0,
        max_dc_vermogen_w=6000.0,
        num_phase=1,
        europees_rendement_pct=97.0,
        geverifieerd=False,
        bron="",
        datasheet_versie="",
        datasheet_datum="",
        opgehaald_op="",
    )
    basis.update(overrides)
    return OmvormerSpec(**basis)


class TestBatterijValidatie:
    def test_geverifieerd_zonder_bron_is_een_fout(self):
        repo = BatterijRepository({("T", "M"): _batterijspec(geverifieerd=True, bron="")})
        bevindingen = controleer_batterijen(repo)

        assert any(b.ernst == "fout" and "geen bron" in b.bericht for b in bevindingen)

    def test_niet_geverifieerd_is_enkel_een_waarschuwing(self):
        repo = BatterijRepository({("T", "M"): _batterijspec(geverifieerd=False)})
        bevindingen = controleer_batterijen(repo)

        assert all(b.ernst != "fout" for b in bevindingen)
        assert any(b.ernst == "waarschuwing" for b in bevindingen)

    def test_geverifieerd_met_bron_geeft_geen_bevinding_over_bron(self):
        repo = BatterijRepository(
            {("T", "M"): _batterijspec(geverifieerd=True, bron="een echte datasheet")}
        )
        bevindingen = controleer_batterijen(repo)

        assert bevindingen == []

    def test_negatieve_capaciteit_is_een_fout(self):
        repo = BatterijRepository({("T", "M"): _batterijspec(max_capacity_kwh=-1.0)})
        bevindingen = controleer_batterijen(repo)

        assert any(b.ernst == "fout" and "max_capacity_kwh" in b.bericht for b in bevindingen)

    def test_rendement_boven_100_procent_is_een_fout(self):
        repo = BatterijRepository({("T", "M"): _batterijspec(round_trip_efficiency_pct=150.0)})
        bevindingen = controleer_batterijen(repo)

        assert any(
            b.ernst == "fout" and "round_trip_efficiency_pct" in b.bericht for b in bevindingen
        )


class TestOmvormerValidatie:
    def test_geverifieerd_zonder_bron_is_een_fout(self):
        repo = OmvormerRepository({("T", "M"): _omvormerspec(geverifieerd=True, bron="")})
        bevindingen = controleer_omvormers(repo)

        assert any(b.ernst == "fout" and "geen bron" in b.bericht for b in bevindingen)

    def test_niet_geverifieerd_is_enkel_een_waarschuwing(self):
        repo = OmvormerRepository({("T", "M"): _omvormerspec(geverifieerd=False)})
        bevindingen = controleer_omvormers(repo)

        assert all(b.ernst != "fout" for b in bevindingen)
        assert any(b.ernst == "waarschuwing" for b in bevindingen)

    def test_negatief_vermogen_is_een_fout(self):
        repo = OmvormerRepository({("T", "M"): _omvormerspec(nominaal_ac_vermogen_w=-1.0)})
        bevindingen = controleer_omvormers(repo)

        assert any(
            b.ernst == "fout" and "nominaal_ac_vermogen_w" in b.bericht for b in bevindingen
        )
