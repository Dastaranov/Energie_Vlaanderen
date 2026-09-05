"""Tests voor `calculation.dispatch.simuleer_ev_laadprofiel`/
`simuleer_warmtepomp_profiel`.

Beide bestaan omdat er geen rijgedrag- of warmtevraagprofiel in dit project
bestaat (in tegenstelling tot PV/batterij, die op SPP/RLP0 kunnen steunen) —
zie hun moduledocstring in `dispatch.py` voor de precieze aanname. Wat hier
vastligt: het jaartotaal komt overeen met de invoer, het laadvenster
respecteert de fysieke laadgrens, en de warmtepomp-COP wordt correct
toegepast (en correct *begrensd* door het nameplate-vermogen).
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from energie_vlaanderen.calculation.dispatch import (
    DispatchError,
    simuleer_ev_laadprofiel,
    simuleer_warmtepomp_profiel,
)
from energie_vlaanderen.calculation.elektrische_wagenSpec import (
    ElektrischeWagen,
    ElektrischeWagenSpec,
)
from energie_vlaanderen.calculation.warmtepompSpec import Warmtepomp, WarmtepompSpec
from energie_vlaanderen.utility.constants import D

pytestmark = pytest.mark.rekenen


def _ev(**overrides) -> ElektrischeWagen:
    spec = ElektrischeWagenSpec(
        merk="Testmerk", model="TW-50", batterij_capaciteit_kwh=50.0,
        verbruik_per_100km_kwh=20.0, max_laadvermogen_ac_w=11000.0,
        max_laadvermogen_dc_w=150000.0, onderhoudsinterval_km=30000.0,
    )
    return ElektrischeWagen.from_masterdata(spec)


def _warmtepomp(**overrides) -> Warmtepomp:
    basis = dict(
        merk="Testmerk", model="TW-10", type_wp="lucht-water",
        max_thermisch_vermogen_w=10000.0, nominaal_elektrisch_vermogen_w=2500.0,
        cop_nominaal=4.0, t_bron_nominaal_c=7.0, t_afgifte_nominaal_c=35.0,
    )
    basis.update(overrides)
    return Warmtepomp.from_masterdata(WarmtepompSpec(**basis))


class TestEvLaadprofiel:
    def test_jaartotaal_klopt_met_km_en_verbruik(self):
        """15.000 km x 20 kWh/100km = 3.000 kWh/jaar."""
        ev = _ev()
        reeks, aanname = simuleer_ev_laadprofiel(
            ev, km_per_jaar=D("15000"), van=date(2026, 1, 1), tot=date(2027, 1, 1),
        )
        assert reeks["kwh"].sum() == pytest.approx(3000.0, rel=1e-6)
        assert aanname.geverifieerd is False

    def test_naar_rato_van_de_periode(self):
        """Een halfjaar geeft de helft van het jaartotaal (pro rata, zelfde
        aanname als `dagaandeel()` elders in dit project)."""
        ev = _ev()
        reeks, _ = simuleer_ev_laadprofiel(
            ev, km_per_jaar=D("15000"), van=date(2026, 1, 1), tot=date(2026, 7, 1),
        )
        dagen = (date(2026, 7, 1) - date(2026, 1, 1)).days
        verwacht = 3000.0 * dagen / 365
        assert reeks["kwh"].sum() == pytest.approx(verwacht, rel=1e-3)

    def test_enkel_binnen_het_laadvenster(self):
        ev = _ev()
        reeks, _ = simuleer_ev_laadprofiel(
            ev, km_per_jaar=D("15000"), van=date(2026, 1, 1), tot=date(2026, 1, 2),
            laadvenster=(22, 6),
        )
        lokaal_uur = pd.to_datetime(reeks["tijdstip"]).dt.tz_convert("Europe/Brussels").dt.hour
        buiten_venster = ~((lokaal_uur >= 22) | (lokaal_uur < 6))
        assert (reeks.loc[buiten_venster, "kwh"] == 0.0).all()
        assert (reeks.loc[~buiten_venster, "kwh"] > 0.0).all()

    def test_weigert_wanneer_het_venster_fysiek_te_kort_is(self):
        """Een EV die 11 kW AC trekt kan in een uur laadvenster nooit
        honderdduizenden kWh per jaar laden."""
        ev = _ev()
        with pytest.raises(DispatchError, match="te kort"):
            simuleer_ev_laadprofiel(
                ev, km_per_jaar=D("500000"), van=date(2026, 1, 1), tot=date(2027, 1, 1),
                laadvenster=(2, 3),
            )


class TestWarmtepompProfiel:
    def test_jaartotaal_zonder_vermogenslimiet(self):
        """Zonder capaciteitslimiet is elektrisch verbruik = thermisch / COP."""
        wp = _warmtepomp()
        n = 8760
        gewichten = pd.DataFrame({
            "tijdstip": pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC"),
            "gewicht": [1.0 / n] * n,
        })
        reeks, aanname = simuleer_warmtepomp_profiel(
            wp, warmtevraag_kwh_jaar=D("20000"), profielgewichten=gewichten,
        )
        assert reeks["kwh"].sum() == pytest.approx(20000.0 / 4.0, rel=1e-6)
        assert aanname.geverifieerd is False

    def test_vermogenslimiet_begrenst_het_elektrisch_verbruik(self):
        """Eén enkel interval met de volledige jaarvraag vraagt een
        thermisch vermogen ver boven `max_thermisch_vermogen_w`; de
        warmtepomp levert dan hooguit haar nameplate-vermogen, dus veel
        minder dan thermisch/COP zou suggereren."""
        wp = _warmtepomp()
        gewichten = pd.DataFrame({
            "tijdstip": pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC"),
            "gewicht": [1.0, 0.0],
        })
        reeks, _ = simuleer_warmtepomp_profiel(
            wp, warmtevraag_kwh_jaar=D("20000"), profielgewichten=gewichten,
        )
        # Max thermisch vermogen 10.000 W over 1 uur = 10 kWh thermisch,
        # gedeeld door COP 4.0 = 2,5 kWh elektrisch — ver onder 20000/4=5000.
        assert reeks["kwh"].iloc[0] == pytest.approx(2.5, rel=1e-6)
