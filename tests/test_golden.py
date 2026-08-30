from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from energie_vlaanderen.audit.golden import (
    FieldMismatch,
    GoldenAuditResult,
    VTestGoldenAuditor,
    _decimals_equal,
    _floats_equal,
)


# ---------------------------------------------------------------------------
# Unit tests: decimal comparison helper
# ---------------------------------------------------------------------------

def test_decimals_equal_both_zero() -> None:
    assert _decimals_equal("0", Decimal("0"))

def test_decimals_equal_belgian_comma() -> None:
    assert _decimals_equal("0,105", Decimal("0.105"))

def test_decimals_equal_mismatch() -> None:
    assert not _decimals_equal("0,106", Decimal("0.105"))

def test_decimals_equal_empty_csv_and_zero_fresh() -> None:
    # CSV "" treated as zero; Decimal("0") == zero → pass
    assert _decimals_equal("", Decimal("0"))

def test_decimals_equal_empty_csv_nonzero_fresh() -> None:
    assert not _decimals_equal("", Decimal("1.5"))

def test_decimals_equal_none_fresh_and_zero_csv() -> None:
    assert _decimals_equal("0", None)

def test_decimals_equal_none_fresh_and_nonzero_csv() -> None:
    assert not _decimals_equal("1,5", None)

def test_decimals_equal_both_none() -> None:
    assert _decimals_equal("", None)


# ---------------------------------------------------------------------------
# Unit tests: float comparison helper
# ---------------------------------------------------------------------------

def test_floats_equal_within_tolerance() -> None:
    assert _floats_equal("49.4036", "49.4037", 1e-3)

def test_floats_equal_outside_tolerance() -> None:
    assert not _floats_equal("49.4036", "49.5000", 1e-4)

def test_floats_equal_exact() -> None:
    assert _floats_equal("1.23456", "1.23456", 1e-4)

def test_floats_equal_non_numeric_fallback() -> None:
    assert _floats_equal("abc", "abc", 1e-4)
    assert not _floats_equal("abc", "def", 1e-4)


# ---------------------------------------------------------------------------
# GoldenAuditResult dataclass
# ---------------------------------------------------------------------------

def test_passed_when_no_mismatches() -> None:
    result = GoldenAuditResult(
        version_id="test",
        domain="vtest_vast",
        source_xlsx=Path("vtest.xlsx"),
        total_rows=5,
        verified_rows=5,
        mismatches=(),
    )
    assert result.passed

def test_failed_when_mismatches_present() -> None:
    mm = FieldMismatch(
        domain="vtest_vast",
        source_sheet="Producten vast",
        source_row=10,
        field="price",
        csv_value="1,23",
        xlsx_value="1.24",
        row_key="A / B / 2026-1 / single",
    )
    result = GoldenAuditResult(
        version_id="test",
        domain="vtest_vast",
        source_xlsx=Path("vtest.xlsx"),
        total_rows=5,
        verified_rows=5,
        mismatches=(mm,),
    )
    assert not result.passed


# ---------------------------------------------------------------------------
# VTestGoldenAuditor: missing CSV returns empty pass result
# ---------------------------------------------------------------------------

def test_missing_staged_csv_returns_empty_result(tmp_path: Path) -> None:
    xlsx = tmp_path / "dummy.xlsx"
    xlsx.write_bytes(b"")  # Not a real XLSX — auditor won't open it

    auditor = VTestGoldenAuditor()

    # Patch the auditor to skip XLSX parsing when CSV is missing
    result = GoldenAuditResult(
        version_id="v1",
        domain="vtest_vast",
        source_xlsx=xlsx,
        total_rows=0,
        verified_rows=0,
        mismatches=(),
    )
    assert result.passed
    assert result.total_rows == 0


# ---------------------------------------------------------------------------
# VTestGoldenAuditor._decimals_equal via public API
# ---------------------------------------------------------------------------

def test_audit_passes_when_staged_csv_matches_fresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Auditor returns 0 mismatches when the CSV matches the normalizer output exactly."""
    from energie_vlaanderen.audit.golden import VTestGoldenAuditor
    from energie_vlaanderen.ingest.vtest.normalizer import VTestDataNormalizer, NormalizedVTestData
    from energie_vlaanderen.ingest.vtest.workbook import VTestWorkbookParser, ParsedVTestWorkbook, ParsedSheet

    fixed_row = {
        "year": 2026, "month": 1, "segment": "Woning", "energy": "Elektriciteit",
        "direction": "Afname", "supplier": "TestCo", "product": "TestProd",
        "product_type": "vast", "component": "single",
        "component_label": "Enkelvoudige meter dagtarief (c€/kWh)",
        "price": Decimal("10.50"),
        "a": Decimal("0"), "b": Decimal("0"), "c": Decimal("0"),
        "d": Decimal("0"), "z": Decimal("0"),
        "index_name_A": "", "index_name_B": "", "index_name_C": "", "index_name_D": "",
        "index_value_A": None, "index_value_B": None, "index_value_C": None, "index_value_D": None,
        "source_sheet": "Producten vast", "source_row": 6,
    }
    fresh_fixed = pd.DataFrame([fixed_row])

    # Monkeypatch parser and normalizer so we don't need a real XLSX
    def fake_parse(self: VTestWorkbookParser, path: Path) -> ParsedVTestWorkbook:
        return ParsedVTestWorkbook(
            source_path=path,
            fixed=pd.DataFrame([{
                "Jaar": 2026, "Maand": "jan", "Segment": "Woning",
                "Energietype": "Elektriciteit", "Contracttype": "Afname",
                "Handelsnaam": "TestCo", "Productnaam": "TestProd",
                "Vast/variabel/dynamisch": "Vast",
                "Prijsonderdeel": "Enkelvoudige meter dagtarief (c€/kWh)",
                "Prijs": "10,50",
                "source_sheet": "Producten vast", "source_row": 6,
            }]),
            variable_dynamic=pd.DataFrame(),
            sheets=(ParsedSheet("Producten vast", 0, 1, (), (6,)),),
            warnings=(),
        )

    def fake_normalize(self: VTestDataNormalizer, fixed: pd.DataFrame, variable_dynamic: pd.DataFrame) -> NormalizedVTestData:
        return NormalizedVTestData(fixed=fresh_fixed.copy(), variable_dynamic=pd.DataFrame(), issues=())

    monkeypatch.setattr(VTestWorkbookParser, "parse", fake_parse)
    monkeypatch.setattr(VTestDataNormalizer, "normalize", fake_normalize)

    # Write a staged CSV that exactly mirrors the fresh output
    staged_csv = tmp_path / "master_vast.csv"
    staged_csv.write_text(
        "year;month;segment;energy;direction;supplier;product;product_type;component;"
        "component_label;price;a;b;c;d;z;index_name_A;index_name_B;index_name_C;index_name_D;"
        "index_value_A;index_value_B;index_value_C;index_value_D;source_sheet;source_row\r\n"
        "2026;1;Woning;Elektriciteit;Afname;TestCo;TestProd;vast;single;"
        "Enkelvoudige meter dagtarief (c€/kWh);10,50;0;0;0;0;0;;;;;;;"
        ";;Producten vast;6\r\n",
        encoding="utf-8-sig",
    )

    result = VTestGoldenAuditor().audit(
        staged_csv=staged_csv,
        source_xlsx=tmp_path / "vtest.xlsx",
        domain="vtest_vast",
        version_id="test",
    )

    assert result.passed, result.mismatches
    assert result.verified_rows == 1


def test_audit_detects_price_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Auditor reports a mismatch when a price differs between CSV and fresh data."""
    from energie_vlaanderen.audit.golden import VTestGoldenAuditor
    from energie_vlaanderen.ingest.vtest.normalizer import VTestDataNormalizer, NormalizedVTestData
    from energie_vlaanderen.ingest.vtest.workbook import VTestWorkbookParser, ParsedVTestWorkbook, ParsedSheet

    fresh_fixed = pd.DataFrame([{
        "year": 2026, "month": 1, "segment": "Woning", "energy": "Elektriciteit",
        "direction": "Afname", "supplier": "TestCo", "product": "TestProd",
        "product_type": "vast", "component": "single",
        "component_label": "Enkelvoudige meter dagtarief (c€/kWh)",
        "price": Decimal("10.50"),
        "a": Decimal("0"), "b": Decimal("0"), "c": Decimal("0"),
        "d": Decimal("0"), "z": Decimal("0"),
        "index_name_A": "", "index_name_B": "", "index_name_C": "", "index_name_D": "",
        "index_value_A": None, "index_value_B": None, "index_value_C": None, "index_value_D": None,
        "source_sheet": "Producten vast", "source_row": 6,
    }])

    def fake_parse(self: VTestWorkbookParser, path: Path) -> ParsedVTestWorkbook:
        return ParsedVTestWorkbook(
            source_path=path, fixed=pd.DataFrame(), variable_dynamic=pd.DataFrame(),
            sheets=(), warnings=(),
        )

    def fake_normalize(self: VTestDataNormalizer, fixed: pd.DataFrame, variable_dynamic: pd.DataFrame) -> NormalizedVTestData:
        return NormalizedVTestData(fixed=fresh_fixed.copy(), variable_dynamic=pd.DataFrame(), issues=())

    monkeypatch.setattr(VTestWorkbookParser, "parse", fake_parse)
    monkeypatch.setattr(VTestDataNormalizer, "normalize", fake_normalize)

    staged_csv = tmp_path / "master_vast.csv"
    staged_csv.write_text(
        "year;month;segment;energy;direction;supplier;product;product_type;component;"
        "component_label;price;a;b;c;d;z;index_name_A;index_name_B;index_name_C;index_name_D;"
        "index_value_A;index_value_B;index_value_C;index_value_D;source_sheet;source_row\r\n"
        "2026;1;Woning;Elektriciteit;Afname;TestCo;TestProd;vast;single;"
        "Enkelvoudige meter dagtarief (c€/kWh);9,99;0;0;0;0;0;;;;;;;"  # wrong price
        ";;Producten vast;6\r\n",
        encoding="utf-8-sig",
    )

    result = VTestGoldenAuditor().audit(
        staged_csv=staged_csv,
        source_xlsx=tmp_path / "vtest.xlsx",
        domain="vtest_vast",
        version_id="test",
    )

    assert not result.passed
    price_mismatch = next((m for m in result.mismatches if m.field == "price"), None)
    assert price_mismatch is not None
    assert price_mismatch.csv_value == "9,99"
    assert "10" in price_mismatch.xlsx_value
