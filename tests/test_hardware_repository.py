"""Tests voor de batterij-/omvormermasterdata in config/hardware/.

Enkel de cijfers die rechtstreeks uit een echte fabrikantdatasheet komen
worden hier als vaststaand gecontroleerd (met paginaverwijzing in de
testdocstring, net als bij `test_transport_tarieven.py`). Velden die in het
TOML-bestand zelf al als schatting/modelaanname becommentarieerd staan
(standby-verbruik, RTE-opsplitsing, ramp-up-tijd, EoL-criterium) worden hier
niet als feit vastgelegd — dat zou precies de fout herhalen die CLAUDE.md's
"Tests: herkomst boven aantal"-sectie beschrijft.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from energie_vlaanderen.hardware.repository import (
    BatterijRepository,
    HardwareError,
    OmvormerRepository,
)

BATTERIJEN_DIR = Path(__file__).resolve().parents[1] / "config" / "hardware" / "batterijen"
OMVORMERS_DIR = Path(__file__).resolve().parents[1] / "config" / "hardware" / "omvormers"


pytestmark = pytest.mark.masterdata


@pytest.fixture(scope="module")
def batterij_repo() -> BatterijRepository:
    return BatterijRepository.load(BATTERIJEN_DIR)


@pytest.fixture(scope="module")
def omvormer_repo() -> OmvormerRepository:
    return OmvormerRepository.load(OMVORMERS_DIR)


class TestMasterdata:
    def test_marstek_venus_e_kerncijfers_uit_de_datasheet(self, batterij_repo):
        """5,12 kWh, >6000 cycli, DoD 90%, 2,5 kVA laad/ontlaad — rechtstreeks
        uit data/datasheets/battery/plug_and_play/VENUS-E-3.0-datasheet.pdf,
        specificatietabel pagina 2.

        `smax_apparent_power_w` stond hier eerder op 3500, met "3,5 kVA piek
        (10s)" als verantwoording. Die 3,5 kVA staat wel degelijk in de
        datasheet, maar onder *Back-up (Off Grid)*: "Max. Apparent Output Power
        3.5kVA, 10s". Dat is een off-grid piek van tien seconden.

        Het veld betekent iets anders: `Smax` uit de Synergrid C10/26-lijst, het
        continu schijnbaar vermogen op het net. De datasheet noemt daarvoor
        onder *AC Input/Output (On Grid)* "Rated Output Power 2.5kVA / 800VA",
        en C10/26 homologeert dit toestel dan ook in twee varianten:
        GLV265-07-0004 op 2500 VA en GLV265-07-0002 op 800 VA.

        Twee grootheden door elkaar dus — een off-grid piek in een veld voor
        on-grid continu vermogen, 40% te hoog. Gevonden door
        `energievergelijker audit hardware --c10-26`.
        """
        spec = batterij_repo.batterij("Marstek", "Venus E")

        assert spec.max_capacity_kwh == pytest.approx(5.12)
        assert spec.max_cycle == 6000
        assert spec.max_depth_of_discharge_pct == pytest.approx(90.0)
        assert spec.max_charge_w == pytest.approx(2500.0)
        assert spec.max_discharge_w == pytest.approx(2500.0)
        assert spec.smax_apparent_power_w == pytest.approx(2500.0)
        assert spec.synergrid_id == "GLV265-07-0004"

    def test_marstek_venus_e_4_0_kerncijfers_uit_de_datasheet(self, batterij_repo):
        """5024 Wh (314 Ah x 5S), >10000 cycli, DoD 88%, 3 kVA laad/ontlaad —
        rechtstreeks uit
        data/datasheets/battery/plug_and_play/MARSTEK_VENUS-4.0.pdf,
        specificatietabel pagina 2. De "4.0" in de modelnaam is een
        SKU-nummer, geen kWh-aanduiding."""
        spec = batterij_repo.batterij("Marstek", "Venus E 4.0")

        assert spec.max_capacity_kwh == pytest.approx(5.024)
        assert spec.max_cycle == 10000
        assert spec.max_depth_of_discharge_pct == pytest.approx(88.0)
        assert spec.max_charge_w == pytest.approx(3000.0)
        assert spec.smax_apparent_power_w == pytest.approx(3600.0)

    def test_marstek_venus_e_mini_kerncijfers_uit_de_datasheet(self, batterij_repo):
        """2009,6 Wh (314 Ah x 2S), >10000 cycli, DoD 90%, 1,5 kVA
        laad/ontlaad — rechtstreeks uit
        data/datasheets/battery/plug_and_play/VENUS_E_Mini.pdf,
        specificatietabel pagina 2."""
        spec = batterij_repo.batterij("Marstek", "Venus E Mini")

        assert spec.max_capacity_kwh == pytest.approx(2.0096)
        assert spec.max_cycle == 10000
        assert spec.max_depth_of_discharge_pct == pytest.approx(90.0)
        assert spec.max_charge_w == pytest.approx(1500.0)

    def test_drie_marstek_modellen_zijn_geladen(self, batterij_repo):
        modellen = sorted(model for _, model in batterij_repo.batterijen())
        assert modellen == ["Venus E", "Venus E 4.0", "Venus E Mini"]

    def test_geen_enkel_batterijmodel_is_al_geverifieerd(self, batterij_repo):
        """Niet omdat de kerncijfers twijfelachtig zijn (die zijn nu net wél
        van een echte datasheet), maar omdat een paar simulatievelden
        (standby-verbruik, RTE-opsplitsing, EoL-criterium) er niet letterlijk
        op staan — zie de bron-comments in elk TOML-bestand."""
        for spec in batterij_repo.batterijen().values():
            assert spec.geverifieerd is False
            assert spec.bron.strip() != ""

    def test_growatt_placeholder_is_expliciet_geen_bron(self, omvormer_repo):
        spec = omvormer_repo.omvormer("Growatt", "SPH 5000")

        assert spec.geverifieerd is False
        assert spec.bron.startswith("GEEN")


class TestOntbrekendeData:
    def test_lege_configmap_faalt_hard(self, tmp_path):
        with pytest.raises(HardwareError, match="Geen batterijbestanden"):
            BatterijRepository.load(tmp_path)

    def test_niet_bestaande_configmap_faalt_hard(self, tmp_path):
        with pytest.raises(HardwareError, match="Geen omvormerbestanden"):
            OmvormerRepository.load(tmp_path / "bestaat-niet")

    def test_onbekend_model_faalt_hard(self, batterij_repo):
        with pytest.raises(HardwareError, match="Onbekend"):
            batterij_repo.batterij("Onbekend", "Model X")

    def test_ontbrekende_sectie_faalt_hard(self, tmp_path):
        (tmp_path / "kapot.toml").write_text('bron = "test"\n')

        with pytest.raises(HardwareError, match="kapot.toml"):
            BatterijRepository.load(tmp_path)

    def test_ontbrekend_verplicht_veld_faalt_hard(self, tmp_path):
        (tmp_path / "kapot.toml").write_text(
            'bron = "test"\n[batterij]\nmerk = "X"\nmodel = "Y"\n'
        )

        with pytest.raises(HardwareError, match="kapot.toml"):
            BatterijRepository.load(tmp_path)

    def test_dubbele_merk_model_sleutel_faalt_hard(self, tmp_path):
        inhoud = _minimale_batterij_toml(merk="Dup", model="Model")
        (tmp_path / "a.toml").write_text(inhoud)
        (tmp_path / "b.toml").write_text(inhoud)

        with pytest.raises(HardwareError, match="Dup"):
            BatterijRepository.load(tmp_path)


def _minimale_batterij_toml(merk: str, model: str) -> str:
    return f"""
bron = "testfixture"
[batterij]
merk = "{merk}"
model = "{model}"
power_control_system = "Hybride"
p_active_power_w = 1000.0
smax_apparent_power_w = 1000.0
num_phase = 1
max_charge_w = 1000.0
max_discharge_w = 1000.0
max_capacity_kwh = 1.0
minimum_capacity_pct = 10.0
standby_power_w = 5.0
round_trip_efficiency_pct = 95.0
rte_ac_dc_pct = 98.0
rte_dc_ac_pct = 98.0
rte_storage_pct = 99.0
ramp_up_time_s = 0.5
max_cycle = 6000
max_depth_of_discharge_pct = 90.0
c_rate = 0.5
eol_criteria_pct = 80.0
"""
