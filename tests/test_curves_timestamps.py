"""Tests voor de tijdstempelconversie in de curves-pipeline.

Aanleiding: 52.560 van de 132.495 curverijen (40%) droegen een ruw
Excel-serienummer in plaats van een tijdstempel. De waarden waren wel correct
ingelezen, maar niet aan een tijdstip te koppelen — en er werd niets over
gerapporteerd.
"""

from __future__ import annotations

import pytest

import pandas as pd

from energie_vlaanderen.ingest.curves.workbook import CurvesWorkbookParser


pytestmark = pytest.mark.parsers


class TestTijdstempelConversie:
    def test_echte_timestamp_blijft_ongewijzigd(self):
        waarde = pd.Timestamp("2027-04-02 06:45:00")

        assert CurvesWorkbookParser._format_ts(waarde) == "2027-04-02T06:45:00"

    def test_excel_serienummer_wordt_een_tijdstempel(self):
        """Geverifieerd tegen het werkblad RLP2027_Elek per kwartier.

        Daar eindigen de correct ingelezen rijen op 2027-04-02 06:45 en is
        46479.291666666664 het eerstvolgende serienummer — dus 07:00.
        """
        assert (
            CurvesWorkbookParser._format_ts(46479.291666666664)
            == "2027-04-02T07:00:00"
        )

    def test_laatste_serienummer_van_het_jaar(self):
        assert (
            CurvesWorkbookParser._format_ts(46752.989583333336)
            == "2027-12-31T23:45:00"
        )

    def test_opeenvolgende_serienummers_geven_kwartierstappen(self):
        stappen = [
            CurvesWorkbookParser._format_ts(46479.291666666664 + i / 96)
            for i in range(4)
        ]

        assert stappen == [
            "2027-04-02T07:00:00",
            "2027-04-02T07:15:00",
            "2027-04-02T07:30:00",
            "2027-04-02T07:45:00",
        ]

    def test_getal_buiten_het_datumbereik_blijft_tekst(self):
        """Een kental mag niet per ongeluk als datum gelezen worden."""
        assert CurvesWorkbookParser._format_ts(0.25) == "0.25"
        assert CurvesWorkbookParser._format_ts(250_000) == "250000"

    def test_tekst_blijft_tekst(self):
        assert CurvesWorkbookParser._format_ts("  2027-01-01  ") == "2027-01-01"

    def test_lege_waarde_geeft_lege_string(self):
        assert CurvesWorkbookParser._format_ts(float("nan")) == ""
