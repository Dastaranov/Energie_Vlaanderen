"""Tests voor calculation/elektrische_wagenSpec.py — de `ElektrischeWagen`.

Een EV is voor deze toepassing vooral een verplaatsbare batterij met een
kilometerteller. Drie dingen kunnen er stil misgaan: een rit die meer verbruikt
dan er in de batterij zit (stranden), een lader die zijn eigen limiet negeert,
en een onderhoudsteller die niet afgaat.

De cijfers zijn deterministische afleidingen uit de invoer van elke test; de
berekening staat in de docstring. Dezelfde afspraak als `test_battery.py`.
"""
from __future__ import annotations

import pytest

from energie_vlaanderen.calculation.elektrische_wagenSpec import (
    ElektrischeWagen,
    ElektrischeWagenSpec,
)


pytestmark = pytest.mark.rekenen


def _wagen(**overrides) -> ElektrischeWagen:
    """50 kWh en 20 kWh/100 km: een actieradius van precies 250 km.

    Ronde waarden zodat elke uitkomst met de hand te volgen is; 11 kW AC en
    150 kW DC zijn realistische ordes van grootte.
    """
    basis = dict(
        merk="Testmerk", model="TW-50", batterij_capaciteit_kwh=50.0,
        verbruik_per_100km_kwh=20.0, max_laadvermogen_ac_w=11000.0,
        max_laadvermogen_dc_w=150000.0, onderhoudsinterval_km=30000.0,
    )
    basis.update(overrides)
    return ElektrischeWagen(**basis)


class TestRijden:
    def test_verbruik_verlaagt_de_lading(self):
        """100 km bij 20 kWh/100 km is 20 kWh van de 50, dus 40 procentpunt:
        de lading gaat van 100 % naar 60 %."""
        wagen = _wagen()
        assert wagen.rijd(100.0) == pytest.approx(100.0)
        assert wagen.state_of_charge_pct == pytest.approx(60.0)

    def test_de_kilometerstand_loopt_mee(self):
        wagen = _wagen()
        wagen.rijd(100.0)
        assert wagen.kilometerstand_km == pytest.approx(100.0)

    def test_stranden_geeft_de_werkelijk_gereden_afstand(self):
        """De belangrijkste van dit bestand. 50 kWh bij 0,2 kWh/km is 250 km;
        wie 400 km vraagt komt 150 km tekort. De methode geeft dan 250 terug en
        niet 400 — een simulatie die 400 km zou boeken, verzint energie."""
        wagen = _wagen()
        assert wagen.rijd(400.0) == pytest.approx(250.0)
        assert wagen.state_of_charge_pct == pytest.approx(0.0)

    def test_stranden_wordt_als_zodanig_gelogd(self):
        wagen = _wagen()
        wagen.rijd(400.0)
        assert "STRANDING" in wagen.geschiedenis[-1]["actie"]

    def test_een_rit_van_nul_of_minder_gebeurt_niet(self):
        wagen = _wagen()
        assert wagen.rijd(0.0) == 0.0
        assert wagen.rijd(-5.0) == 0.0
        assert wagen.kilometerstand_km == 0.0


class TestLaden:
    def test_ac_laden_wordt_begrensd_door_de_boordlader(self):
        """Een paal van 22 kW levert niet meer dan de wagen aankan: bij 11 kW
        AC blijft dat 11 kWh in een uur. Dit is de meest gemaakte fout in een
        laadsimulatie — het vermogen van de paal nemen in plaats van het
        minimum van paal en wagen."""
        wagen = _wagen(state_of_charge_pct=0.0)
        assert wagen.laad(22000.0, 3600.0) == pytest.approx(11.0)

    def test_dc_snelladen_gebruikt_de_andere_limiet(self):
        """Dezelfde 22 kW aan een snellader gaat wél volledig door: de
        DC-limiet is 150 kW."""
        wagen = _wagen(state_of_charge_pct=0.0)
        assert wagen.laad(22000.0, 3600.0, is_dc_snelladen=True) == pytest.approx(22.0)

    def test_laden_stopt_bij_een_volle_batterij(self):
        """Bij 90 % is er nog 5 kWh ruimte; een uur aan 50 kW levert er dus 5,
        niet 11 of 50."""
        wagen = _wagen(state_of_charge_pct=90.0)
        assert wagen.laad(50000.0, 3600.0) == pytest.approx(5.0)
        assert wagen.state_of_charge_pct == pytest.approx(100.0)

    def test_negatieve_duur_faalt_hard(self):
        with pytest.raises(ValueError, match="duur_s"):
            _wagen().laad(11000.0, -1.0)

    def test_laden_zonder_vermogen_levert_niets(self):
        assert _wagen(state_of_charge_pct=50.0).laad(0.0, 3600.0) == 0.0


class TestGrenzen:
    def test_de_lading_wordt_geklemd_tussen_0_en_100(self):
        wagen = _wagen()
        wagen.state_of_charge_pct = 150.0
        assert wagen.state_of_charge_pct == 100.0
        wagen.state_of_charge_pct = -10.0
        assert wagen.state_of_charge_pct == 0.0

    def test_de_kilometerteller_kan_niet_terug(self):
        """Een teller die terugloopt betekent dat twee ritten door elkaar
        lopen, of dat er met de hand geknoeid is. Beide gevallen horen te
        stoppen in plaats van een lagere kilometerstand te aanvaarden."""
        wagen = _wagen()
        wagen.rijd(100.0)
        with pytest.raises(ValueError, match="terugdraaien"):
            wagen.kilometerstand_km = 10.0

    def test_een_negatieve_specificatie_faalt_hard(self):
        with pytest.raises(ValueError, match="negatief"):
            _wagen(batterij_capaciteit_kwh=-50.0)


class TestOnderhoud:
    def test_de_waarschuwing_gaat_af_bij_het_interval(self):
        """Na 30.100 km met een interval van 30.000 hoort de wagen naar de
        garage. De teller telt vanaf het laatste onderhoud, niet vanaf nul."""
        wagen = _wagen()
        wagen.kilometerstand_km = 29900.0
        wagen.rijd(200.0)
        assert wagen.onderhoud_nodig is True
        assert any("Onderhoudsinterval" in r["actie"] for r in wagen.geschiedenis)

    def test_de_waarschuwing_komt_maar_een_keer(self):
        """Blijven waarschuwen bij elke rit maakt het logboek onleesbaar en de
        waarschuwing waardeloos."""
        wagen = _wagen()
        wagen.kilometerstand_km = 29900.0
        wagen.rijd(200.0)
        wagen.laad(150000.0, 3600.0, is_dc_snelladen=True)
        wagen.rijd(100.0)
        aantal = sum("Onderhoudsinterval" in r["actie"] for r in wagen.geschiedenis)
        assert aantal == 1

    def test_onderhoud_zet_de_teller_terug(self):
        wagen = _wagen()
        wagen.kilometerstand_km = 29900.0
        wagen.rijd(200.0)
        wagen.voer_onderhoud_uit()
        assert wagen.onderhoud_nodig is False
        assert wagen.laatste_onderhoud_km == pytest.approx(30100.0)


class TestGeschiedenis:
    def test_aanmaken_logt_de_nieuwstaat(self):
        assert "Aangemaakt" in _wagen().geschiedenis[0]["actie"]

    def test_de_geschiedenis_wordt_een_dataframe(self):
        wagen = _wagen()
        wagen.rijd(50.0)
        frame = wagen.geschiedenis_als_dataframe()
        for kolom in ("stap", "actie", "SoC (%)", "Kilometerstand"):
            assert kolom in frame.columns


class TestFromMasterdata:
    def test_een_tweedehands_wagen_start_met_zijn_kilometerstand(self):
        """En met een onderhoudsteller die daarop staat: anders zou een wagen
        met 80.000 km meteen 'onderhoud nodig' melden."""
        spec = ElektrischeWagenSpec(
            merk="Testmerk", model="TW-50", batterij_capaciteit_kwh=50.0,
            verbruik_per_100km_kwh=20.0, max_laadvermogen_ac_w=11000.0,
            max_laadvermogen_dc_w=150000.0, onderhoudsinterval_km=30000.0,
        )
        wagen = ElektrischeWagen.from_masterdata(spec, huidige_km_stand=80000.0)
        assert wagen.kilometerstand_km == pytest.approx(80000.0)
        assert wagen.laatste_onderhoud_km == pytest.approx(80000.0)
        wagen.rijd(10.0)
        assert wagen.onderhoud_nodig is False
