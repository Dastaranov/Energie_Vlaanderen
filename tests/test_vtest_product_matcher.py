"""Tests voor product_matcher.py — best-effort koppeling tussen de live
vtest.be-scrape (vreg_id) en de VREG-bulk-export (Handelsnaam/Productnaam)."""
from __future__ import annotations

import pandas as pd
import pytest

from energie_vlaanderen.ingest.vtest.product_matcher import (
    match_products,
    normalize_name,
)


pytestmark = pytest.mark.scrape


def _vtest_row(vreg_id, supplier_raw, product_raw, segment="woning", energy="Elektriciteit"):
    return {
        "vreg_id": vreg_id, "supplier_raw": supplier_raw, "product_raw": product_raw,
        "segment": segment, "energy": energy,
    }


def _bulk_row(handelsnaam, productnaam, segment="Woning", energie="Elektriciteit"):
    return {
        "Handelsnaam": handelsnaam, "Productnaam": productnaam,
        "Segment": segment, "Energietype": energie,
    }


class TestNormalizeName:
    def test_lowercases_and_trims(self):
        assert normalize_name("  Belvus Energie  ") == "belvus energie"

    def test_strips_known_suffix(self):
        assert normalize_name("Flex Online Pro EL") == "flex online pro"

    def test_collapses_whitespace(self):
        assert normalize_name("Goedkope   Stroom") == "goedkope stroom"


class TestMatchProducts:
    def test_exact_match(self):
        vtest_df = pd.DataFrame([_vtest_row("1", "EnergyVision", "Goedkope Stroom 3 jaar vast")])
        bulk_df = pd.DataFrame([_bulk_row("EnergyVision", "Goedkope Stroom 3 jaar vast")])
        matches, report = match_products(vtest_df, bulk_df)
        assert matches[0].match_status == "exact"
        assert report.exact == 1
        assert report.geen_match == 0

    def test_normalized_match_on_suffix_difference(self):
        vtest_df = pd.DataFrame([_vtest_row("1", "Belvus", "Flex Online Pro EL")])
        bulk_df = pd.DataFrame([_bulk_row("Belvus", "Flex Online Pro")])
        matches, report = match_products(vtest_df, bulk_df)
        assert matches[0].match_status == "genormaliseerd"
        assert report.genormaliseerd == 1

    def test_no_match_on_both_sides_reported(self):
        vtest_df = pd.DataFrame([_vtest_row("1", "NieuweLeverancier", "Onbekend Product")])
        bulk_df = pd.DataFrame([_bulk_row("AndereLeverancier", "Ander Product")])
        matches, report = match_products(vtest_df, bulk_df)
        assert matches[0].match_status == "geen_match"
        assert report.geen_match == 1
        assert len(report.voorbeelden_vtest_zonder_match) == 1
        assert len(report.voorbeelden_bulk_ongebruikt) == 1

    def test_segment_mismatch_does_not_match(self):
        vtest_df = pd.DataFrame([_vtest_row("1", "Bolt", "Bolt Vast", segment="onderneming")])
        bulk_df = pd.DataFrame([_bulk_row("Bolt", "Bolt Vast", segment="Woning")])
        matches, report = match_products(vtest_df, bulk_df)
        assert matches[0].match_status == "geen_match"

    def test_report_counts_match_totals(self):
        vtest_df = pd.DataFrame([
            _vtest_row("1", "A", "Product A"),
            _vtest_row("2", "B", "Product B"),
            _vtest_row("3", "C", "Product C"),
        ])
        bulk_df = pd.DataFrame([
            _bulk_row("A", "Product A"),
            _bulk_row("B", "Product B EL"),
        ])
        matches, report = match_products(vtest_df, bulk_df)
        assert report.totaal_vtest_producten == 3
        assert report.exact == 1
        assert report.genormaliseerd == 1
        assert report.geen_match == 1
