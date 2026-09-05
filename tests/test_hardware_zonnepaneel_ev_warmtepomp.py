"""Tests voor de zonnepaneel-/EV-/warmtepompmasterdata in `config/hardware/`.

Zelfde regel als `test_hardware_repository.py`: enkel cijfers die
rechtstreeks uit een echte bron komen worden hier vastgelegd, met de bron in
de docstring. Een veld dat het TOML-bestand zelf al als gemodelleerd/afgeleid
markeert (bv. de elektrische opname van de warmtepomp) staat hier niet als
feit.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from energie_vlaanderen.hardware.repository import (
    ElektrischeWagenRepository,
    HardwareError,
    WarmtepompRepository,
    ZonnepaneelRepository,
)

HARDWARE_DIR = Path(__file__).resolve().parents[1] / "config" / "hardware"

pytestmark = pytest.mark.masterdata


@pytest.fixture(scope="module")
def zonnepaneel_repo() -> ZonnepaneelRepository:
    return ZonnepaneelRepository.load(HARDWARE_DIR / "zonnepanelen")


@pytest.fixture(scope="module")
def ev_repo() -> ElektrischeWagenRepository:
    return ElektrischeWagenRepository.load(HARDWARE_DIR / "elektrische_wagens")


@pytest.fixture(scope="module")
def warmtepomp_repo() -> WarmtepompRepository:
    return WarmtepompRepository.load(HARDWARE_DIR / "warmtepompen")


class TestZonnepaneelMasterdata:
    def test_ja_solar_kerncijfers_uit_de_datasheet(self, zonnepaneel_repo):
        """440 W, Voc 37,91 V, Isc 14,58 A — rechtstreeks uit de JA Solar-
        datasheet "JAM54S30 415-440/LR/1500V" (Global_EN_20230522A),
        tabel "ELECTRICAL PARAMETERS AT STC", kolom 440 W."""
        spec = zonnepaneel_repo.zonnepaneel("JA Solar", "JAM54S30-440/LR/1500V")
        assert spec.piekvermogen_wp == 440.0
        assert spec.v_oc_volt == pytest.approx(37.91)
        assert spec.i_sc_ampere == pytest.approx(14.58)
        assert spec.temperatuur_coeff_pmax_pct_c == pytest.approx(-0.350)
        assert spec.geverifieerd is True

    def test_oppervlakte_komt_uit_de_afmetingen(self, zonnepaneel_repo):
        """1762 x 1134 mm uit dezelfde datasheet, tabel "SPECIFICATIONS"."""
        spec = zonnepaneel_repo.zonnepaneel("JA Solar", "JAM54S30-440/LR/1500V")
        assert spec.oppervlakte_m2 == pytest.approx(1.762 * 1.134, rel=1e-3)


class TestElektrischeWagenMasterdata:
    def test_id3_pro_kerncijfers_uit_ev_database(self, ev_repo):
        """58 kWh netto, 11 kW AC, 124 kW DC — EV Database, geraadpleegd
        2026-09-05. `geverifieerd = false`: geen eerstehandsbron."""
        spec = ev_repo.elektrische_wagen("Volkswagen", "ID.3 Pro")
        assert spec.batterij_capaciteit_kwh == 58.0
        assert spec.max_laadvermogen_ac_w == 11000.0
        assert spec.max_laadvermogen_dc_w == 124000.0
        assert spec.geverifieerd is False


class TestWarmtepompMasterdata:
    def test_altherma_cop_bij_a7_w35(self, warmtepomp_repo):
        """COP 4,86 bij A7/W35 (EN14511) — rechtstreeks uit de Daikin-
        installateursdatasheet, kolom "Heating (e)"."""
        spec = warmtepomp_repo.warmtepomp("Daikin", "Altherma 3 H HT EPRA16DV3")
        assert spec.cop_nominaal == pytest.approx(4.86)
        assert spec.t_bron_nominaal_c == 7.0
        assert spec.t_afgifte_nominaal_c == 35.0

    def test_elektrisch_vermogen_is_thermisch_gedeeld_door_cop(self, warmtepomp_repo):
        """Niet gepubliceerd, dus het TOML-bestand zelf leidt het af — deze
        test toetst enkel dat die afleiding klopt, niet dat het cijfer een
        feit is."""
        spec = warmtepomp_repo.warmtepomp("Daikin", "Altherma 3 H HT EPRA16DV3")
        verwacht = spec.max_thermisch_vermogen_w / spec.cop_nominaal
        assert spec.nominaal_elektrisch_vermogen_w == pytest.approx(verwacht, rel=1e-3)


def test_onbekend_model_geeft_een_leesbare_fout(zonnepaneel_repo):
    with pytest.raises(HardwareError, match="Geen zonnepaneelmasterdata"):
        zonnepaneel_repo.zonnepaneel("Onbekend", "X")
