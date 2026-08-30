"""Tests voor TariffDataNormalizer — voetnootfilter en basisstructuur."""
from __future__ import annotations

import pandas as pd
import pytest

from energie_vlaanderen.ingest.tariffs.normalizer import TariffDataNormalizer


def _elek_row(col0, desc, digi=None, ana=None, pro=None, sheet="FA ELEK Afname", source_row=10):
    """Bouw een minimale elektriciteitsrij met de vereiste kolomindices."""
    # Kolommen: 0=col0, 1=desc, 2=x, 3=unit, 4-12=x, 13=DIGI, 14=ANA, 15=ANA_PRO
    data = [col0, desc] + [None] * 11 + [digi, ana, pro]
    return {i: v for i, v in enumerate(data)} | {"source_sheet": sheet, "source_row": source_row}


def _make_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _normalizer():
    return TariffDataNormalizer()


class TestVoetnootFilter:
    """Voetnootrijen mogen nooit in de output terechtkomen."""

    def test_dash_footnote_filtered(self):
        rows = [
            _elek_row("1", "Tarieven voor het netgebruik"),
            _elek_row("", "Gemiddelde maandpiek", digi=49.40, ana=45.00, pro=45.00),
            _elek_row("", "- Deze tarieflijst geldt van 01/01/2026 t.e.m. 31/12/2026.", digi=0.27),
        ]
        df = _make_frame(rows)
        result = _normalizer().normalize(df, pd.DataFrame())
        details = result.afname["Tariefdetail"].tolist()
        assert not any(d.startswith("- ") for d in details), "Dash-voetnoten mogen niet in output staan"

    def test_star_footnote_filtered(self):
        rows = [
            _elek_row("1", "Tarieven voor het netgebruik"),
            _elek_row("", "kWh-tarief", digi=0.023),
            _elek_row("", "*1 Aandeel transmissienetkosten in 'Tarieven voor het netgebruik'", digi=0.268),
        ]
        df = _make_frame(rows)
        result = _normalizer().normalize(df, pd.DataFrame())
        details = result.afname["Tariefdetail"].tolist()
        assert not any(d.startswith("*") for d in details), "Ster-voetnoten mogen niet in output staan"

    def test_real_tariff_rows_kept(self):
        rows = [
            _elek_row("1", "Tarieven voor het netgebruik"),
            _elek_row("", "Gemiddelde maandpiek", digi=49.40, ana=45.00, pro=45.00),
            _elek_row("", "kWh-tarief", digi=0.023, ana=0.023, pro=0.023),
            _elek_row("", "- Footnote zonder prijs"),
        ]
        df = _make_frame(rows)
        result = _normalizer().normalize(df, pd.DataFrame())
        details = result.afname["Tariefdetail"].tolist()
        assert "Gemiddelde maandpiek" in details
        assert "kWh-tarief" in details
        assert len(details) == 6  # 2 tariefdetails × 3 klanttypes

    def test_footnote_with_price_still_filtered(self):
        """Een voetnoot met prijs is geen tariefregel — ook filteren."""
        rows = [
            _elek_row("1", "Aanvullend capaciteitstarief"),
            _elek_row("", "Aanvullend capaciteitstarief voor prosumenten", pro=51.54),
            _elek_row("", "- Aanbieders van vraagresponsdiensten...", pro=1.56),
        ]
        df = _make_frame(rows)
        result = _normalizer().normalize(df, pd.DataFrame())
        details = result.afname["Tariefdetail"].tolist()
        assert not any(d.startswith("- ") for d in details)


class TestNormalizerOutput:
    """Basisstructuur van de genormaliseerde output."""

    def test_output_columns_present(self):
        rows = [
            _elek_row("1", "Tarieven voor het netgebruik"),
            _elek_row("", "Gemiddelde maandpiek", digi=49.40),
        ]
        result = _normalizer().normalize(_make_frame(rows), pd.DataFrame())
        for col in ("Netbeheerder", "Contracttype", "Tarieftype", "Tariefdetail",
                    "Tariefnotering", "Klanttype", "Prijs_num", "source_sheet", "source_row"):
            assert col in result.afname.columns, f"Kolom {col} ontbreekt in output"

    def test_klanttype_mapped_correctly(self):
        rows = [
            _elek_row("1", "Netgebruik"),
            _elek_row("", "Capaciteit", digi=49.0, ana=45.0, pro=51.0),
        ]
        result = _normalizer().normalize(_make_frame(rows), pd.DataFrame())
        klanttypes = set(result.afname["Klanttype"])
        assert klanttypes == {"ELEK_LS_DIGI", "ELEK_LS_ANA", "ELEK_LS_ANA_PRO"}

    def test_row_without_price_skipped(self):
        rows = [
            _elek_row("1", "Netgebruik"),
            _elek_row("", "Vaste term"),  # geen prijs → geen output
        ]
        result = _normalizer().normalize(_make_frame(rows), pd.DataFrame())
        assert result.afname.empty

    def test_empty_input_returns_empty(self):
        result = _normalizer().normalize(pd.DataFrame(), pd.DataFrame())
        assert result.afname.empty
        assert result.injectie.empty

    def test_unknown_dnb_code_skipped(self):
        rows = [
            _elek_row("1", "Tarieven", sheet="ONBEKEND ELEK Afname"),
            _elek_row("", "kWh-tarief", digi=0.02, sheet="ONBEKEND ELEK Afname"),
        ]
        result = _normalizer().normalize(_make_frame(rows), pd.DataFrame())
        assert result.afname.empty
