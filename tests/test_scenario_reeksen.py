"""Tests voor `scenario.reeksen.dag_nacht_masker`/`verdeel_dag_nacht`.

Ontstaan uit een echte fout: een eerdere versie van `BatterijScenario`/
`ZonnepaneelScenario` zette de gesimuleerde meting altijd in één
`afname_kwh`-kolom. `Kostberekening._periodevolumes()` valt dan terug op
"alles is dagverbruik" (`som("afname_dag_kwh") or som("afname_kwh")`) — voor
een contract met een dag/nacht-tariefverschil rekent dat systematisch te veel
aan, en voor een EV die juist 's nachts laadt draait het de bedoeling van het
scenario om. Tegen de echte databank gaf het toevoegen van zonnepanelen zo een
gestegen in plaats van een gedaalde kost.
"""
from __future__ import annotations

import pandas as pd
import pytest

from energie_vlaanderen.scenario.reeksen import dag_nacht_masker, verdeel_dag_nacht

pytestmark = pytest.mark.dossier


def _metingen(**kolommen) -> pd.DataFrame:
    tijdstip = pd.date_range("2026-01-01", periods=4, freq="15min", tz="UTC")
    return pd.DataFrame({"tijdstip": tijdstip, **kolommen})


class TestDagNachtMasker:
    def test_geen_dag_nacht_kolommen_geeft_niets(self):
        metingen = _metingen(afname_kwh=[1.0, 2.0, 3.0, 4.0])
        assert dag_nacht_masker(metingen) is None

    def test_geen_metingen_geeft_niets(self):
        assert dag_nacht_masker(None) is None
        assert dag_nacht_masker(pd.DataFrame({"tijdstip": [], "afname_dag_kwh": []})) is None

    def test_herkent_dag_en_nacht_per_interval(self):
        metingen = _metingen(
            afname_dag_kwh=[1.0, 0.0, 0.5, 0.0],
            afname_nacht_kwh=[0.0, 1.0, 0.0, 0.5],
        )
        masker = dag_nacht_masker(metingen)
        assert list(masker["is_dag"]) == [True, False, True, False]

    def test_gebruikt_ook_injectieregisters(self):
        """Een interval met enkel injectie (geen afname) moet ook zijn
        dag/nacht-herkomst behouden."""
        metingen = _metingen(
            afname_dag_kwh=[0.0, 0.0, 0.0, 0.0],
            afname_nacht_kwh=[0.0, 0.0, 0.0, 0.0],
            injectie_dag_kwh=[0.5, 0.0, 0.0, 0.0],
            injectie_nacht_kwh=[0.0, 0.5, 0.0, 0.0],
        )
        masker = dag_nacht_masker(metingen)
        assert list(masker["is_dag"])[:2] == [True, False]


class TestVerdeelDagNacht:
    def test_zonder_masker_komt_alles_in_het_dagslot_met_waarschuwing(self):
        reeks = pd.DataFrame({
            "tijdstip": pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC"),
            "kwh": [1.0, 2.0],
        })
        gesplitst, waarschuwing = verdeel_dag_nacht(reeks, None, "afname")
        assert list(gesplitst["afname_dag_kwh"]) == [1.0, 2.0]
        assert list(gesplitst["afname_nacht_kwh"]) == [0.0, 0.0]
        assert waarschuwing is not None
        assert "dag/nacht" in waarschuwing

    def test_met_masker_volgt_het_register_van_het_oorspronkelijke_interval(self):
        tijdstip = pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC")
        masker = pd.DataFrame({"tijdstip": tijdstip, "is_dag": [True, False, True]})
        reeks = pd.DataFrame({"tijdstip": tijdstip, "kwh": [1.0, 2.0, 3.0]})

        gesplitst, waarschuwing = verdeel_dag_nacht(reeks, masker, "afname")

        assert waarschuwing is None
        assert list(gesplitst["afname_dag_kwh"]) == [1.0, 0.0, 3.0]
        assert list(gesplitst["afname_nacht_kwh"]) == [0.0, 2.0, 0.0]

    def test_ev_nachtladen_belandt_dus_effectief_in_het_nachtregister(self):
        """De regressietest voor de fout zelf: 's nachts geladen energie moet
        na de splitsing in het nachtregister staan, niet in het dagregister."""
        tijdstip = pd.date_range("2026-01-01 22:00", periods=4, freq="h", tz="UTC")
        # Vier nachtelijke uren, allemaal 'nacht' volgens de meting.
        masker = pd.DataFrame({"tijdstip": tijdstip, "is_dag": [False, False, False, False]})
        laadprofiel = pd.DataFrame({"tijdstip": tijdstip, "kwh": [2.0, 2.0, 2.0, 2.0]})

        gesplitst, _ = verdeel_dag_nacht(laadprofiel, masker, "afname")

        assert gesplitst["afname_dag_kwh"].sum() == 0.0
        assert gesplitst["afname_nacht_kwh"].sum() == 8.0
