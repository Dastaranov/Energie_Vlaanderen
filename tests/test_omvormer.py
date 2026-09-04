"""Tests voor calculation/omvormerSpec.py — de zelfbewakende `Omvormer`.

De klasse bewaakt haar eigen grenzen via `__setattr__` en houdt elke wijziging
bij in een logboek. Dat is precies het soort code waar tests iets waard zijn:
de invarianten moeten gelden wát je er ook op loslaat, en een grens die stil
niet werkt levert een plausibel maar verkeerd energiegetal op.

De cijfers hieronder zijn geen externe feiten maar deterministische afleidingen
uit de invoer van elke test; de berekening staat telkens in de docstring. Dat is
onder "herkomst boven aantal" (CLAUDE.md) een citeerbare herkomst — dezelfde
afspraak die `test_battery.py` hanteert.
"""
from __future__ import annotations

import pytest

from energie_vlaanderen.calculation.omvormerSpec import Omvormer


pytestmark = pytest.mark.rekenen


def _omvormer(**overrides) -> Omvormer:
    """Ronde, makkelijk na te rekenen waarden — geen reëel productmodel.

    5 kW AC met 7,5 kW DC erachter is een gangbare verhouding (overdimensionering
    van het paneelveld), en juist die verhouding maakt het AC-plafond zichtbaar.
    """
    basis = dict(
        merk="Testmerk", model="TM-5000", product_type="pv",
        nominaal_ac_vermogen_w=5000.0, max_ac_vermogen_w=5000.0,
        max_dc_vermogen_w=7500.0, num_phase=1, europees_rendement_pct=96.0,
    )
    basis.update(overrides)
    return Omvormer(**basis)


class TestGrenzen:
    def test_belasting_wordt_geklemd_tussen_0_en_100(self):
        omvormer = _omvormer()
        omvormer.actuele_belasting_pct = 150.0
        assert omvormer.actuele_belasting_pct == 100.0
        omvormer.actuele_belasting_pct = -20.0
        assert omvormer.actuele_belasting_pct == 0.0

    def test_negatieve_nameplate_faalt_hard(self):
        """Een nameplate-waarde is een gegeven van de fabrikant, geen
        toestand. Negatief betekent een leesfout, en die hoort te stoppen in
        plaats van door te rekenen.

        Een negatief vermogen valt in de strengere controle ("groter dan nul"),
        want daar deelt de fysica door; de lopende totalen mogen wél nul zijn
        en worden alleen op negatief getoetst.
        """
        with pytest.raises(ValueError, match="groter dan nul"):
            _omvormer(max_ac_vermogen_w=-1.0)

        omvormer = _omvormer()
        with pytest.raises(ValueError, match="negatief"):
            omvormer.totaal_geleverde_ac_energie_kwh = -1.0

    def test_rendement_buiten_het_bereik_faalt_hard(self):
        with pytest.raises(ValueError, match="percentage"):
            _omvormer(europees_rendement_pct=140.0)

    def test_negatieve_duur_faalt_hard(self):
        with pytest.raises(ValueError, match="duur_s"):
            _omvormer().dc_naar_ac(1000.0, -1.0)


class TestDcNaarAc:
    def test_rendement_wordt_toegepast(self):
        """1000 W gedurende 3600 s is 1 kWh DC; bij 96 % blijft 0,96 kWh AC over."""
        assert _omvormer().dc_naar_ac(1000.0, 3600.0) == pytest.approx(0.96)

    def test_de_belasting_volgt_de_dc_limiet(self):
        """1000 van 7500 W is 13,33 % — de belasting van een PV-omvormer wordt
        aan de DC-kant gemeten, want daar zit de begrenzing."""
        omvormer = _omvormer()
        omvormer.dc_naar_ac(1000.0, 3600.0)
        assert omvormer.actuele_belasting_pct == pytest.approx(1000 / 7500 * 100)

    def test_het_ac_plafond_knipt_de_levering_af(self):
        """Dit is waarom een omvormer geen doorgeefluik is.

        9000 W aangeboden wordt eerst geklemd op de DC-limiet van 7500 W; dat
        is 7,5 kWh over een uur, maal 96 % is 7,2 kWh. Maar het AC-plafond laat
        maar 5000 W x 1 h = 5 kWh door. Er komt dus 5,0 kWh uit, niet 7,2 —
        precies het verlies dat een overgedimensioneerd paneelveld oplevert.
        """
        assert _omvormer().dc_naar_ac(9000.0, 3600.0) == pytest.approx(5.0)

    def test_nul_vermogen_levert_niets_en_zet_de_belasting_terug(self):
        omvormer = _omvormer()
        omvormer.dc_naar_ac(1000.0, 3600.0)
        assert omvormer.dc_naar_ac(0.0, 3600.0) == 0.0
        assert omvormer.actuele_belasting_pct == 0.0

    def test_de_geleverde_energie_telt_op(self):
        omvormer = _omvormer()
        omvormer.dc_naar_ac(1000.0, 3600.0)
        omvormer.dc_naar_ac(1000.0, 3600.0)
        assert omvormer.totaal_geleverde_ac_energie_kwh == pytest.approx(1.92)


class TestAcNaarDc:
    def test_rendement_wordt_toegepast(self):
        """De andere richting, voor het laden van een batterij: 1 kWh AC bij
        96 % geeft 0,96 kWh DC."""
        assert _omvormer().ac_naar_dc(1000.0, 3600.0) == pytest.approx(0.96)

    def test_de_belasting_volgt_hier_de_ac_limiet(self):
        """Bij laden zit de begrenzing aan de netzijde, dus de belasting wordt
        tegen `max_ac_vermogen_w` gemeten en niet tegen de DC-limiet."""
        omvormer = _omvormer()
        omvormer.ac_naar_dc(1000.0, 3600.0)
        assert omvormer.actuele_belasting_pct == pytest.approx(1000 / 5000 * 100)


class TestGeschiedenis:
    def test_aanmaken_logt_de_eerste_regel(self):
        assert _omvormer().geschiedenis[0]["actie"] == "Aangemaakt"

    def test_een_begrensde_waarde_wordt_als_zodanig_gelogd(self):
        """Een stille begrenzing is een verloren feit: het verschil tussen
        "er kwam 5 kWh uit" en "er kwam 5 kWh uit omdat de rest niet paste"."""
        omvormer = _omvormer()
        omvormer.actuele_belasting_pct = 150.0
        assert "begrensd" in omvormer.geschiedenis[-1]["actie"]

    def test_wis_geschiedenis_laat_een_regel_over(self):
        omvormer = _omvormer()
        omvormer.dc_naar_ac(1000.0, 3600.0)
        omvormer.wis_geschiedenis()
        assert len(omvormer.geschiedenis) == 1
        assert omvormer.geschiedenis[0]["actie"] == "Geschiedenis gewist"

    def test_de_geschiedenis_wordt_een_dataframe(self):
        omvormer = _omvormer()
        omvormer.dc_naar_ac(1000.0, 3600.0)
        frame = omvormer.geschiedenis_als_dataframe()
        for kolom in ("stap", "actie", "actuele_belasting_pct", "totaal_ac_kwh"):
            assert kolom in frame.columns


class TestNulVermogen:
    """Een nameplate van nul watt maakt de fysica ongedefinieerd.

    De belasting is een percentage van het maximum, en zonder maximum bestaat
    dat percentage niet. Nul werd aanvaard omdat het niet negatief is, waarna
    `dc_naar_ac` afbrak met een `ZeroDivisionError` — een onbegrijpelijke fout
    op wat in werkelijkheid een invoerprobleem is.

    Nu geweigerd bij het aanmaken, met de reden erbij. Bij elke deling opnieuw
    bewaken zou hetzelfde effect hebben, maar dan staat de regel op drie
    plaatsen en moet je hem bij elke nieuwe deling onthouden.
    """

    @pytest.mark.parametrize("veld", [
        "max_dc_vermogen_w", "max_ac_vermogen_w", "nominaal_ac_vermogen_w",
    ])
    def test_nul_wordt_geweigerd_met_een_leesbare_melding(self, veld):
        with pytest.raises(ValueError, match="groter dan nul"):
            _omvormer(**{veld: 0.0})

    def test_negatief_blijft_ook_geweigerd(self):
        with pytest.raises(ValueError):
            _omvormer(max_dc_vermogen_w=-1.0)

    def test_de_lopende_totalen_mogen_wel_nul_zijn(self):
        """Die staan in dezelfde groep als "niet negatief" maar beginnen
        vanzelfsprekend op nul; ze strikt positief eisen zou elke nieuwe
        omvormer onmaakbaar maken."""
        omvormer = _omvormer()
        assert omvormer.totaal_geleverde_ac_energie_kwh == 0.0
        assert omvormer.totaal_geleverde_dc_energie_kwh == 0.0
