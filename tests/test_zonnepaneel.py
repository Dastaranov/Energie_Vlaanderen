"""Tests voor calculation/zonnepaneelSpec.py — het `Zonnepaneel` met degradatie.

De klasse rekent instraling, celtemperatuur en ouderdom om naar DC-vermogen. Elk
van die drie kan stil een verkeerd getal opleveren: een tekenfout in de
temperatuurcoëfficiënt maakt hitte gunstig, en een degradatie die niet
doorwerkt geeft een paneel van twintig jaar de opbrengst van een nieuw.

De cijfers zijn deterministische afleidingen uit de invoer van elke test; de
berekening staat in de docstring. Eén vast punt is wél een extern feit: bij STC
(1000 W/m², 25 °C) levert een nieuw paneel per definitie zijn piekvermogen —
dat ís de betekenis van Wp.
"""
from __future__ import annotations

import pytest

from energie_vlaanderen.calculation.zonnepaneelSpec import Zonnepaneel, ZonnepaneelSpec


pytestmark = pytest.mark.rekenen


def _paneel(**overrides) -> Zonnepaneel:
    """Een gangbaar 400 Wp-paneel met ronde waarden.

    De coëfficiënten zijn realistisch van orde van grootte (-0,35 %/°C voor
    vermogen, -0,25 %/°C voor spanning) maar afgerond, zodat elke uitkomst met
    de hand na te rekenen is.
    """
    basis = dict(
        merk="Testmerk", model="TP-400", piekvermogen_wp=400.0,
        v_oc_volt=50.0, i_sc_ampere=10.0, v_mpp_volt=42.0, i_mpp_ampere=9.5,
        temperatuur_coeff_pmax_pct_c=-0.35, temperatuur_coeff_voc_pct_c=-0.25,
        degradatie_eerste_jaar_pct=2.0, degradatie_per_jaar_pct=0.5,
        oppervlakte_m2=1.95,
    )
    basis.update(overrides)
    return Zonnepaneel(**basis)


class TestStandaardTestcondities:
    def test_een_nieuw_paneel_levert_bij_stc_zijn_piekvermogen(self):
        """1000 W/m² bij 25 °C en leeftijd nul: geen temperatuurcorrectie, geen
        degradatie. De uitkomst moet exact het nameplate-vermogen zijn — dat is
        de definitie van Wp, niet een benadering."""
        assert _paneel().genereer_dc_vermogen(1000.0, 25.0) == pytest.approx(400.0)

    def test_de_werkspanning_is_bij_25_graden_de_mpp_spanning(self):
        paneel = _paneel()
        paneel.genereer_dc_vermogen(1000.0, 25.0)
        assert paneel.actuele_spanning_v == pytest.approx(42.0)

    def test_het_vermogen_schaalt_lineair_met_de_instraling(self):
        """500 van 1000 W/m² is de helft: 200 W."""
        assert _paneel().genereer_dc_vermogen(500.0, 25.0) == pytest.approx(200.0)


class TestTemperatuur:
    def test_hitte_kost_vermogen(self):
        """45 °C is 20 graden boven STC. Bij -0,35 %/°C is dat -7 %:
        400 x 0,93 = 372 W. Een tekenfout hier zou hitte gunstig maken."""
        assert _paneel().genereer_dc_vermogen(1000.0, 45.0) == pytest.approx(372.0)

    def test_hitte_verlaagt_ook_de_spanning(self):
        """42 V x (1 - 0,25 % x 20) = 39,9 V. De spanning telt voor de omvormer:
        bij kou stijgt ze juist, en te hoog betekent uitval."""
        paneel = _paneel()
        paneel.genereer_dc_vermogen(1000.0, 45.0)
        assert paneel.actuele_spanning_v == pytest.approx(39.9)

    def test_kou_levert_meer_vermogen_dan_stc(self):
        """0 °C is 25 graden onder STC: 400 x (1 + 0,35 % x 25) = 435 W."""
        assert _paneel().genereer_dc_vermogen(1000.0, 0.0) == pytest.approx(435.0)


class TestDegradatie:
    def test_een_nieuw_paneel_degradeert_niet(self):
        assert _paneel()._bereken_degradatie_factor() == 1.0

    def test_het_eerste_jaar_kost_twee_procent(self):
        """De initiële degradatie (LID) is eenmalig en groter dan de jaarlijkse:
        na één jaar 400 x 0,98 = 392 W."""
        paneel = _paneel()
        paneel.verouder(1.0)
        assert paneel.genereer_dc_vermogen(1000.0, 25.0) == pytest.approx(392.0)

    def test_daarna_is_het_verlies_lineair(self):
        """Na vijf jaar: 2 % initieel plus vier maal 0,5 % is 4 % totaal,
        dus 400 x 0,96 = 384 W. Zou de eerste-jaarsdegradatie elk jaar
        toegepast worden, dan stond hier 400 x 0,90."""
        paneel = _paneel()
        paneel.verouder(5.0)
        assert paneel.genereer_dc_vermogen(1000.0, 25.0) == pytest.approx(384.0)

    def test_verouderen_stapelt(self):
        paneel = _paneel()
        paneel.verouder(1.0)
        paneel.verouder(4.0)
        assert paneel.leeftijd_jaren == pytest.approx(5.0)
        assert paneel.genereer_dc_vermogen(1000.0, 25.0) == pytest.approx(384.0)

    def test_een_paneel_kan_niet_jonger_worden(self):
        with pytest.raises(ValueError, match="jonger"):
            _paneel().verouder(-1.0)

    def test_de_gezondheid_zakt_nooit_onder_nul(self):
        """Bij 400 jaar zou het lineaire verlies boven 100 % uitkomen; een
        negatieve opbrengst bestaat niet."""
        paneel = _paneel()
        paneel.verouder(400.0)
        assert paneel._bereken_degradatie_factor() == 0.0
        assert paneel.genereer_dc_vermogen(1000.0, 25.0) == pytest.approx(0.0)


class TestGrenzen:
    def test_zonder_instraling_geen_vermogen_en_terug_naar_nullast(self):
        """'s Nachts levert het paneel niets, maar staat er wél spanning: de
        open-klemspanning. Dat onderscheid telt voor de omvormer."""
        paneel = _paneel()
        paneel.genereer_dc_vermogen(1000.0, 25.0)
        assert paneel.genereer_dc_vermogen(0.0, 25.0) == 0.0
        assert paneel.actuele_spanning_v == pytest.approx(50.0)

    def test_het_vermogen_wordt_geklemd_op_anderhalf_maal_het_piekvermogen(self):
        """Boven STC kan een paneel kortstondig meer leveren (het cloud-edge-
        effect), maar niet onbeperkt. 1,5 x 400 = 600 W is de bovengrens."""
        paneel = _paneel()
        paneel.actueel_vermogen_w = 9999.0
        assert paneel.actueel_vermogen_w == pytest.approx(600.0)

    def test_negatief_vermogen_wordt_op_nul_geklemd(self):
        paneel = _paneel()
        paneel.actueel_vermogen_w = -50.0
        assert paneel.actueel_vermogen_w == 0.0

    def test_een_negatieve_nameplate_faalt_hard(self):
        with pytest.raises(ValueError, match="fysiek onmogelijk"):
            _paneel(piekvermogen_wp=-400.0)


class TestGeschiedenis:
    def test_aanmaken_logt_de_nieuwstaat(self):
        assert "Aangemaakt" in _paneel().geschiedenis[0]["actie"]

    def test_verouderen_logt_de_gezondheid(self):
        paneel = _paneel()
        paneel.verouder(5.0)
        laatste = paneel.geschiedenis[-1]["actie"]
        assert "Verouderd" in laatste and "96.0%" in laatste

    def test_de_opwek_zelf_vervuilt_het_logboek_niet(self):
        """Vermogen en spanning wijzigen bij elk kwartier van een simulatie. Ze
        elk loggen zou het logboek onleesbaar maken en de geheugendruk laten
        meegroeien met de simulatieduur; alleen gebeurtenissen worden gelogd."""
        paneel = _paneel()
        voor = len(paneel.geschiedenis)
        for _ in range(50):
            paneel.genereer_dc_vermogen(800.0, 30.0)
        assert len(paneel.geschiedenis) == voor

    def test_de_geschiedenis_wordt_een_dataframe(self):
        paneel = _paneel()
        paneel.verouder(1.0)
        frame = paneel.geschiedenis_als_dataframe()
        for kolom in ("stap", "actie", "Leeftijd (jaren)", "Vermogen (W)"):
            assert kolom in frame.columns


class TestFromMasterdata:
    def test_de_specificatie_wordt_overgenomen(self):
        spec = ZonnepaneelSpec(
            merk="Testmerk", model="TP-400", piekvermogen_wp=400.0,
            v_oc_volt=50.0, i_sc_ampere=10.0, v_mpp_volt=42.0, i_mpp_ampere=9.5,
            temperatuur_coeff_pmax_pct_c=-0.35, temperatuur_coeff_voc_pct_c=-0.25,
        )
        paneel = Zonnepaneel.from_masterdata(spec)
        assert paneel.piekvermogen_wp == 400.0
        assert paneel.degradatie_eerste_jaar_pct == 2.0, "standaardwaarde uit de spec"
        assert paneel.leeftijd_jaren == 0.0

    def test_een_bestaand_paneel_start_met_zijn_leeftijd(self):
        """Een installatie van tien jaar oud hoort niet als nieuw doorgerekend
        te worden: 2 % plus negen maal 0,5 % is 6,5 % verlies."""
        spec = ZonnepaneelSpec(
            merk="Testmerk", model="TP-400", piekvermogen_wp=400.0,
            v_oc_volt=50.0, i_sc_ampere=10.0, v_mpp_volt=42.0, i_mpp_ampere=9.5,
            temperatuur_coeff_pmax_pct_c=-0.35, temperatuur_coeff_voc_pct_c=-0.25,
        )
        paneel = Zonnepaneel.from_masterdata(spec, start_leeftijd_jaren=10.0)
        assert paneel.genereer_dc_vermogen(1000.0, 25.0) == pytest.approx(400 * 0.935)
