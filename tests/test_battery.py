"""Tests voor calculation/batterySpec.py — bestond nog niet, ondanks dat de
klasse al maanden in gebruik was via het demo-script.

De cijfers die hier vastgelegd worden, zijn geen externe feiten maar
deterministische afleidingen uit de eigen invoerwaarden van elke test (de
berekening staat uitgeschreven in de docstring, net als
`test_transport_tarieven.py` dat doet met een vtest.be-bron) — dat is onder
"herkomst boven aantal" een geldige, citeerbare herkomst.
"""
from __future__ import annotations

import pytest

from energie_vlaanderen.calculation.batterySpec import Battery
from energie_vlaanderen.hardware.models import BatterijSpec


pytestmark = pytest.mark.rekenen


def _kale_batterij(**overrides) -> Battery:
    """Een batterij met ronde, makkelijk na te rekenen testwaarden — geen
    reëel productmodel, uitsluitend om de `Battery`-mechaniek zelf te
    toetsen."""
    basis = dict(
        synergrid_id="TEST-0001",
        merknaam="Testmerk",
        productnaam="Testmodel",
        power_control_system="Hybride",
        P_active_power=2.0,
        Smax_apparent_power=2.0,
        num_phase=1,
        max_charge_w=2000.0,
        max_discharge_w=1500.0,
        max_capacity=10.0,
        minimum_capacity=10.0,
        standby_power_w=100.0,
        round_trip_efficiency=95.0,
        rte_ac_dc=98.0,
        rte_dc_ac=96.0,
        rte_storage=99.0,
        ramp_up_time=1.0,
        max_cycle=1000,
        max_depth_of_discharge=90.0,
        state_of_charge=50.0,
        state_of_health=100.0,
        c_rate=0.5,
        eol_criteria=80.0,
    )
    basis.update(overrides)
    return Battery(**basis)


class TestKlemgedrag:
    def test_state_of_charge_boven_100_wordt_geklemd(self):
        batterij = _kale_batterij()
        batterij.state_of_charge = 150.0

        assert batterij.state_of_charge == 100.0

    def test_state_of_charge_onder_minimum_capacity_wordt_geklemd(self):
        """De ondergrens is minimum_capacity (10%), niet 0% — een BMS laat
        de cel nooit dieper zakken dan de fabrikant toestaat."""
        batterij = _kale_batterij(minimum_capacity=10.0)
        batterij.state_of_charge = -20.0

        assert batterij.state_of_charge == 10.0

    def test_state_of_health_wordt_geklemd_tussen_0_en_100(self):
        batterij = _kale_batterij()
        batterij.state_of_health = 150.0
        assert batterij.state_of_health == 100.0

        batterij.state_of_health = -50.0
        assert batterij.state_of_health == 0.0

    def test_negatieve_nameplate_specificatie_faalt_hard(self):
        with pytest.raises(ValueError, match="max_capacity"):
            _kale_batterij(max_capacity=-1.0)

    def test_percentageveld_buiten_bereik_faalt_hard(self):
        with pytest.raises(ValueError, match="minimum_capacity"):
            _kale_batterij(minimum_capacity=150.0)


class TestLaadEnOntlaad:
    def test_laden_zonder_verzadiging(self):
        """2000 W x 3600 s = 2,0 kWh AC-aanbod. x 0,98 (rte_ac_dc) = 1,96 kWh
        DC. Ruimte tot vol = 10,0 - (10,0 x 50%) = 5,0 kWh > 1,96 kWh, dus
        geen begrenzing: SoC stijgt met (1,96/10,0) x 100 = 19,6 punt, van
        50% naar 69,6%, en het teruggegeven AC-verbruik is exact de
        aangeboden 2,0 kWh (1,96 / 0,98)."""
        batterij = _kale_batterij(state_of_charge=50.0)

        opgenomen_ac = batterij.laad(vermogen_w=2000.0, duur_s=3600.0)

        assert opgenomen_ac == pytest.approx(2.0)
        assert batterij.state_of_charge == pytest.approx(69.6)

    def test_laden_wordt_begrensd_door_de_resterende_ruimte(self):
        """Bij 50% SoC is er nog maar 5,0 kWh ruimte tot vol. Een aanbod van
        20,0 kWh AC (2000 W x 10 uur) x 0,98 = 19,6 kWh DC wordt dus
        afgekapt op 5,0 kWh: SoC eindigt exact op 100%, en het teruggegeven
        AC-verbruik is 5,0 / 0,98 ≈ 5,102 kWh — niet de volledige 20,0 kWh
        die aangeboden werd."""
        batterij = _kale_batterij(state_of_charge=50.0)

        opgenomen_ac = batterij.laad(vermogen_w=2000.0, duur_s=36000.0)

        assert batterij.state_of_charge == pytest.approx(100.0)
        assert opgenomen_ac == pytest.approx(5.0 / 0.98, rel=1e-6)

    def test_laadvermogen_wordt_begrensd_door_max_charge_w(self):
        """5000 W gevraagd, max_charge_w = 2000 W: het resultaat moet
        identiek zijn aan expliciet 2000 W vragen."""
        batterij_hoog = _kale_batterij(state_of_charge=50.0)
        batterij_referentie = _kale_batterij(state_of_charge=50.0)

        resultaat_hoog = batterij_hoog.laad(vermogen_w=5000.0, duur_s=3600.0)
        resultaat_referentie = batterij_referentie.laad(vermogen_w=2000.0, duur_s=3600.0)

        assert resultaat_hoog == pytest.approx(resultaat_referentie)

    def test_ontladen_zonder_verzadiging(self):
        """1500 W x 3600 s = 1,5 kWh AC-vraag. / 0,96 (rte_dc_ac) = 1,5625
        kWh DC benodigd. Beschikbaar boven de ondergrens (10%) is
        10,0 x (50%-10%) = 4,0 kWh > 1,5625 kWh, dus geen begrenzing: SoC
        daalt met (1,5625/10,0) x 100 = 15,625 punt, van 50% naar 34,375%,
        en de geleverde AC-energie is exact de gevraagde 1,5 kWh
        (1,5625 x 0,96)."""
        batterij = _kale_batterij(state_of_charge=50.0)

        geleverd_ac = batterij.ontlaad(vermogen_w=1500.0, duur_s=3600.0)

        assert geleverd_ac == pytest.approx(1.5)
        assert batterij.state_of_charge == pytest.approx(34.375)

    def test_ontladen_wordt_begrensd_door_de_minimum_capacity(self):
        """Bij 15% SoC is er nog maar 10,0 x (15%-10%) = 0,5 kWh beschikbaar
        boven de ondergrens. Een vraag van 1,5 kWh AC wordt dus afgekapt:
        SoC eindigt exact op de ondergrens (10%)."""
        batterij = _kale_batterij(state_of_charge=15.0, minimum_capacity=10.0)

        batterij.ontlaad(vermogen_w=1500.0, duur_s=3600.0)

        assert batterij.state_of_charge == pytest.approx(10.0)

    def test_verbruik_standby_trekt_af_tot_de_ondergrens(self):
        """100 W x 3600 s = 0,1 kWh, ruim onder de 4,0 kWh die beschikbaar is
        boven de ondergrens bij 50% SoC: SoC daalt met
        (0,1/10,0) x 100 = 1,0 punt naar 49%."""
        batterij = _kale_batterij(state_of_charge=50.0)

        verbruikt = batterij.verbruik_standby(duur_s=3600.0)

        assert verbruikt == pytest.approx(0.1)
        assert batterij.state_of_charge == pytest.approx(49.0)

    def test_negatieve_duur_faalt_hard(self):
        batterij = _kale_batterij()
        with pytest.raises(ValueError, match="duur_s"):
            batterij.laad(vermogen_w=1000.0, duur_s=-1.0)


class TestGeschiedenis:
    def test_aanmaken_logt_de_eerste_regel(self):
        batterij = _kale_batterij()
        assert len(batterij.geschiedenis) == 1
        assert batterij.geschiedenis[0]["actie"] == "Aangemaakt"

    def test_elke_wijziging_wordt_gelogd(self):
        batterij = _kale_batterij()
        batterij.laad(vermogen_w=500.0, duur_s=3600.0)

        assert len(batterij.geschiedenis) == 2

    def test_wis_geschiedenis_laat_één_regel_over(self):
        batterij = _kale_batterij()
        batterij.laad(vermogen_w=500.0, duur_s=3600.0)

        batterij.wis_geschiedenis()

        assert len(batterij.geschiedenis) == 1
        assert batterij.geschiedenis[0]["actie"] == "Geschiedenis gewist"

    def test_geschiedenis_als_dataframe_bevat_de_kerncolommen(self):
        batterij = _kale_batterij()
        df = batterij.geschiedenis_als_dataframe()

        for kolom in ("stap", "actie", "state_of_charge", "state_of_health"):
            assert kolom in df.columns


class TestFromMasterdata:
    def _spec(self, **overrides) -> BatterijSpec:
        basis = dict(
            merk="Testmerk",
            model="Testmodel",
            synergrid_id="TEST-0001",
            power_control_system="Hybride",
            p_active_power_w=2000.0,
            smax_apparent_power_w=2000.0,
            num_phase=1,
            max_charge_w=2000.0,
            max_discharge_w=1500.0,
            max_capacity_kwh=10.0,
            minimum_capacity_pct=10.0,
            standby_power_w=100.0,
            round_trip_efficiency_pct=95.0,
            rte_ac_dc_pct=98.0,
            rte_dc_ac_pct=96.0,
            rte_storage_pct=99.0,
            ramp_up_time_s=1.0,
            max_cycle=1000,
            max_depth_of_discharge_pct=90.0,
            c_rate=0.5,
            eol_criteria_pct=80.0,
            geverifieerd=False,
            bron="testfixture",
            datasheet_versie="",
            datasheet_datum="",
            opgehaald_op="",
        )
        basis.update(overrides)
        return BatterijSpec(**basis)

    def test_veldmapping_1_op_1(self):
        spec = self._spec()
        batterij = Battery.from_masterdata(spec)

        assert batterij.merknaam == "Testmerk"
        assert batterij.productnaam == "Testmodel"
        assert batterij.max_charge_w == 2000.0
        assert batterij.max_discharge_w == 1500.0
        assert batterij.max_capacity == 10.0
        assert batterij.minimum_capacity == 10.0
        assert batterij.max_cycle == 1000
        assert batterij.max_depth_of_discharge == 90.0

    def test_runtime_toestand_start_op_nieuwstaat_tenzij_anders_gevraagd(self):
        spec = self._spec()

        standaard = Battery.from_masterdata(spec)
        assert standaard.state_of_charge == 100.0
        assert standaard.state_of_health == 100.0

        aangepast = Battery.from_masterdata(spec, state_of_charge=40.0, state_of_health=90.0)
        assert aangepast.state_of_charge == 40.0
        assert aangepast.state_of_health == 90.0


class TestNulCycli:
    """`max_cycle` staat in de noemer van het cyclusverlies.

    Het verlies per cyclus is het bereik tot de EOL-drempel gedeeld door het
    aantal cycli; bij nul brak dat af met een `ZeroDivisionError`. Dezelfde
    fout als in `omvormerSpec`, en om dezelfde reden bij de bron geweigerd:
    een batterij die nul cycli meegaat is geen batterij, en een
    ZeroDivisionError verbergt dat het om een invoerprobleem gaat.
    """

    def test_nul_cycli_wordt_geweigerd_met_een_leesbare_melding(self):
        with pytest.raises(ValueError, match="groter dan nul"):
            _kale_batterij(max_cycle=0)

    def test_negatieve_cycli_worden_ook_geweigerd(self):
        with pytest.raises(ValueError, match="groter dan nul"):
            _kale_batterij(max_cycle=-1)

    def test_een_normale_batterij_blijft_werken(self):
        assert _kale_batterij().max_cycle == 1000
