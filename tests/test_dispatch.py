"""Tests voor `calculation.dispatch.simuleer_batterij_dispatch`.

Vier kwartieren, met de hand na te rekenen: twee met een productieoverschot
(laden), twee met een tekort (ontladen). De batterij is dezelfde
"kale batterij" als `test_battery.py` gebruikt — ronde getallen, geen reëel
productmodel, uitsluitend om de dispatchlus zelf te toetsen.
"""
from __future__ import annotations

import pandas as pd
import pytest

from energie_vlaanderen.calculation.batterySpec import Battery
from energie_vlaanderen.calculation.dispatch import DispatchError, simuleer_batterij_dispatch
from energie_vlaanderen.gebruikers.models import Topologie

pytestmark = pytest.mark.rekenen


def _kale_batterij(**overrides) -> Battery:
    basis = dict(
        synergrid_id="TEST-0001", merknaam="Testmerk", productnaam="Testmodel",
        power_control_system="Hybride", P_active_power=2.0, Smax_apparent_power=2.0,
        num_phase=1, max_charge_w=2000.0, max_discharge_w=1500.0, max_capacity=10.0,
        minimum_capacity=10.0, standby_power_w=0.0, round_trip_efficiency=95.0,
        rte_ac_dc=100.0, rte_dc_ac=100.0, rte_storage=100.0, ramp_up_time=1.0,
        max_cycle=1000, max_depth_of_discharge=90.0, state_of_charge=50.0,
        state_of_health=100.0, c_rate=0.5, eol_criteria=80.0,
    )
    basis.update(overrides)
    return Battery(**basis)


def _kwartieren(waarden: list[float]) -> pd.DataFrame:
    tijdstippen = pd.date_range("2026-01-01", periods=len(waarden), freq="15min", tz="UTC")
    return pd.DataFrame({"tijdstip": tijdstippen, "kwh": waarden})


class TestZelfconsumptieEerst:
    def test_overschot_laadt_de_batterij(self):
        """1 kWh productie, 0,4 kWh verbruik -> 0,6 kWh overschot per kwartier.

        Bij 100% RTE en een ruime laadcapaciteit (2000 W = 0,5 kWh/kwartier
        maximaal, maar hier wordt in 15 minuten 0,6 kWh aangeboden aan
        2400 W — boven max_charge_w=2000 W) wordt het laadvermogen begrensd
        tot 2000 W, dus 0,5 kWh geladen en 0,1 kWh naar injectie.
        """
        batterij = _kale_batterij()
        # Een tweede, neutraal kwartier zodat de mediane tijdstap af te leiden
        # is — `intervalduur_uren()` heeft minstens twee tijdstippen nodig.
        verbruik = _kwartieren([0.4, 0.0])
        productie = _kwartieren([1.0, 0.0])

        resultaat = simuleer_batterij_dispatch(
            batterij, verbruik, productie, topologie=Topologie.DC_GEKOPPELD,
        )

        assert resultaat.loc[0, "afname_kwh"] == pytest.approx(0.0)
        assert resultaat.loc[0, "batterij_laad_kwh"] == pytest.approx(0.5)
        assert resultaat.loc[0, "injectie_kwh"] == pytest.approx(0.1)

    def test_tekort_ontlaadt_de_batterij(self):
        """0,2 kWh productie, 0,7 kWh verbruik -> 0,5 kWh tekort per kwartier,
        ruim binnen max_discharge_w (1500 W = 0,375 kWh/kwartier) en de
        beschikbare energie boven de minimumgrens (50% van 10 kWh = 5 kWh,
        ondergrens 10% = 1 kWh, dus 4 kWh beschikbaar) — dus volledig uit de
        batterij, geen afname van het net."""
        batterij = _kale_batterij()
        verbruik = _kwartieren([0.7, 0.0])
        productie = _kwartieren([0.2, 0.0])

        resultaat = simuleer_batterij_dispatch(
            batterij, verbruik, productie, topologie=Topologie.DC_GEKOPPELD,
        )

        # max_discharge_w=1500W begrenst tot 0,375 kWh in dit kwartier
        assert resultaat.loc[0, "batterij_ontlaad_kwh"] == pytest.approx(0.375)
        assert resultaat.loc[0, "afname_kwh"] == pytest.approx(0.5 - 0.375)
        assert resultaat.loc[0, "injectie_kwh"] == pytest.approx(0.0)

    def test_volle_batterij_laat_overschot_naar_injectie_gaan(self):
        """Een batterij die al vol is (SoC 100%) kan niets meer opnemen — het
        volledige overschot moet dan naar injectie, niet verdwijnen."""
        batterij = _kale_batterij(state_of_charge=100.0)
        verbruik = _kwartieren([0.0, 0.0])
        productie = _kwartieren([0.3, 0.0])

        resultaat = simuleer_batterij_dispatch(
            batterij, verbruik, productie, topologie=Topologie.DC_GEKOPPELD,
        )

        assert resultaat.loc[0, "batterij_laad_kwh"] == pytest.approx(0.0)
        assert resultaat.loc[0, "injectie_kwh"] == pytest.approx(0.3)

    def test_soc_wordt_meegegeven_per_interval(self):
        batterij = _kale_batterij(state_of_charge=50.0)
        verbruik = _kwartieren([0.0, 0.0])
        productie = _kwartieren([0.5, 0.5])

        resultaat = simuleer_batterij_dispatch(
            batterij, verbruik, productie, topologie=Topologie.DC_GEKOPPELD,
        )

        assert resultaat.loc[0, "batterij_soc_pct"] < resultaat.loc[1, "batterij_soc_pct"]


def _uren(prijzen: list[float]) -> pd.DataFrame:
    tijdstippen = pd.date_range("2026-01-01", periods=len(prijzen), freq="h", tz="UTC")
    return pd.DataFrame({"tijdstip": tijdstippen, "kwh": [0.0] * len(prijzen)})


def _markt(prijzen: list[float]) -> pd.DataFrame:
    tijdstippen = pd.date_range("2026-01-01", periods=len(prijzen), freq="h", tz="UTC")
    return pd.DataFrame({"timestamp": tijdstippen, "price_eur_mwh": prijzen})


class TestPrijsarbitrage:
    """Twee volle dagen, telkens 6 goedkope, 12 gewone en 4 dure uren — de
    batterij (4 kWh, 2 kW laad/ontlaad) kan in 2 uur volledig laden en heeft
    dus exact de 2 goedkoopste uren als koopdrempel nodig, en 2 uur om van
    90% bruikbare capaciteit (max_depth_of_discharge) te ontladen als
    verkoopdrempel."""

    def _batterij(self, **overrides) -> Battery:
        basis = dict(
            synergrid_id="TEST", merknaam="Test", productnaam="Test",
            power_control_system="Hybride", P_active_power=2.0, Smax_apparent_power=2.0,
            num_phase=1, max_charge_w=2000.0, max_discharge_w=2000.0, max_capacity=4.0,
            minimum_capacity=10.0, standby_power_w=0.0, round_trip_efficiency=100.0,
            rte_ac_dc=100.0, rte_dc_ac=100.0, rte_storage=100.0, ramp_up_time=1.0,
            max_cycle=1000, max_depth_of_discharge=90.0, state_of_charge=50.0,
            state_of_health=100.0, c_rate=0.5, eol_criteria=80.0,
        )
        basis.update(overrides)
        return Battery(**basis)

    def _prijzen_twee_dagen(self) -> list[float]:
        een_dag = [20.0] * 6 + [80.0] * 12 + [200.0] * 4 + [80.0] * 2
        return een_dag * 2

    def _verbruik_met_bestaande_piek(self, lengte: int) -> pd.DataFrame:
        """0,5 kWh/uur, behalve één piekuur (12u, los van de arbitrage-uren)
        met 5 kWh — een huishouden met een bestaande piek die niets met de
        prijs te maken heeft. Die piek (5 kWh/uur) is de piekgrens waaronder
        arbitragekoop nog mag laden."""
        waarden = [0.5] * lengte
        for i in range(12, lengte, 24):
            waarden[i] = 5.0
        return pd.DataFrame({
            "tijdstip": pd.date_range("2026-01-01", periods=lengte, freq="h", tz="UTC"),
            "kwh": waarden,
        })

    def test_laadt_maximaal_tijdens_de_goedkoopste_uren(self):
        batterij = self._batterij(state_of_charge=50.0)
        prijzen = self._prijzen_twee_dagen()
        verbruik = self._verbruik_met_bestaande_piek(len(prijzen))
        resultaat = simuleer_batterij_dispatch(
            batterij, verbruik, _uren(prijzen), topologie=Topologie.DC_GEKOPPELD,
            marktprijzen=_markt(prijzen),
        )
        # Uur 0-1 (20 EUR/MWh, 0,5 kWh bestaand verbruik): de bestaande
        # piek van die maand (5 kWh, om 12u) laat hier ruim plaats voor
        # de volle 2 kW laadvermogen — laadt van 50% naar 100%.
        assert resultaat.loc[0, "modus"] == "arbitrage_koop"
        assert resultaat.loc[1, "batterij_soc_pct"] == pytest.approx(100.0)

    def test_arbitragekoop_overschrijdt_de_bestaande_piek_niet(self):
        """Zonder headroom (bestaand verbruik zelf al op de maandpiek) mag
        arbitragekoop niets bijladen — anders verhoogt de "besparing" op de
        energiekost het capaciteitstarief."""
        batterij = self._batterij(state_of_charge=50.0)
        prijzen = self._prijzen_twee_dagen()
        # Constant verbruik gelijk aan wat de batterij als laadvermogen zou
        # willen nemen: geen enkel uur heeft headroom onder de piek van de
        # maand (die piek is exact dit constante verbruik).
        verbruik = _uren([2.0] * len(prijzen))
        resultaat = simuleer_batterij_dispatch(
            batterij, verbruik, _uren(prijzen), topologie=Topologie.DC_GEKOPPELD,
            marktprijzen=_markt(prijzen),
        )
        assert resultaat.loc[0, "batterij_laad_kwh"] == pytest.approx(0.0)
        assert resultaat.loc[0, "batterij_soc_pct"] == pytest.approx(50.0)

    def test_verkoopt_maximaal_tijdens_de_duurste_uren(self):
        batterij = self._batterij(state_of_charge=50.0)
        prijzen = self._prijzen_twee_dagen()
        resultaat = simuleer_batterij_dispatch(
            batterij, _uren(prijzen), _uren(prijzen), topologie=Topologie.DC_GEKOPPELD,
            marktprijzen=_markt(prijzen),
        )
        # Uur 18-19 (200 EUR/MWh, index 18-19): ontlaadt tot de minimumgrens (10%).
        assert resultaat.loc[18, "modus"] == "arbitrage_verkoop"
        assert resultaat.loc[19, "batterij_soc_pct"] == pytest.approx(10.0)
        assert resultaat.loc[18, "injectie_kwh"] > 0

    def test_blijft_zelfconsumptie_tussen_de_drempels(self):
        batterij = self._batterij(state_of_charge=50.0)
        prijzen = self._prijzen_twee_dagen()
        resultaat = simuleer_batterij_dispatch(
            batterij, _uren(prijzen), _uren(prijzen), topologie=Topologie.DC_GEKOPPELD,
            marktprijzen=_markt(prijzen),
        )
        # Uur 6-17 (80 EUR/MWh, "normale" prijs): geen productie/verbruik, dus
        # geen enkele reden om te bewegen.
        for i in range(6, 18):
            assert resultaat.loc[i, "modus"] == "zelfconsumptie"
            assert resultaat.loc[i, "afname_kwh"] == 0.0

    def test_zonder_marktprijzen_ongewijzigd_zelfconsumptie(self):
        """Regressietoets: `marktprijzen=None` mag het bestaande gedrag niet
        raken — de arbitragecode is puur additief."""
        batterij_met = self._batterij(state_of_charge=50.0)
        batterij_zonder = self._batterij(state_of_charge=50.0)
        verbruik = _kwartieren([0.7, 0.0])
        productie = _kwartieren([0.2, 0.0])

        met = simuleer_batterij_dispatch(
            batterij_met, verbruik, productie, topologie=Topologie.DC_GEKOPPELD,
            marktprijzen=None,
        )
        zonder = simuleer_batterij_dispatch(
            batterij_zonder, verbruik, productie, topologie=Topologie.DC_GEKOPPELD,
        )
        pd.testing.assert_series_equal(met["afname_kwh"], zonder["afname_kwh"])
        pd.testing.assert_series_equal(met["injectie_kwh"], zonder["injectie_kwh"])
        assert (met["modus"] == "zelfconsumptie").all()

    def test_te_kort_prijsvenster_wordt_geweigerd(self):
        batterij = self._batterij()
        verbruik = _uren([50.0] * 4)
        markt = _markt([50.0] * 3)  # één uur te weinig
        with pytest.raises(DispatchError, match="geen marktprijs"):
            simuleer_batterij_dispatch(
                batterij, verbruik, verbruik, topologie=Topologie.DC_GEKOPPELD,
                marktprijzen=markt,
            )


def test_te_veel_ontbrekende_tijdstippen_wordt_geweigerd():
    batterij = _kale_batterij()
    verbruik = _kwartieren([0.1] * 20)
    productie = pd.DataFrame({"tijdstip": [verbruik["tijdstip"][0]], "kwh": [0.1]})

    with pytest.raises(DispatchError, match="komen niet in beide reeksen voor"):
        simuleer_batterij_dispatch(batterij, verbruik, productie, topologie=Topologie.DC_GEKOPPELD)
