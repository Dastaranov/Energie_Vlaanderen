"""De poort tussen normaliseren en wegschrijven.

Twee soorten controle. Per rij: een vast product zonder prijs is een fout, een
variabel product zonder prijs maar mét formule niet. En over het geheel: elke
bronrij moet precies één keer in precies één tabel terechtkomen — een rij die in
beide tabellen belandt of stil verdwijnt wordt hier gevonden.
"""
from __future__ import annotations

import pytest

from decimal import Decimal
from pathlib import Path

import pandas as pd

from energie_vlaanderen.ingest.vtest.validator import VTestDataValidator
from energie_vlaanderen.ingest.vtest.workbook import ParsedSheet, ParsedVTestWorkbook


pytestmark = pytest.mark.parsers


def make_row() -> dict[str, object]:
    return {
        "year": 2026,
        "month": 8,
        "segment": "Woning",
        "energy": "Elektriciteit",
        "direction": "Afname",
        "supplier": "Leverancier A",
        "product": "Product A",
        "product_type": "vast",
        "component": "single",
        "component_label": "Enkelvoudige meter dagtarief",
        "price": Decimal("30.50"),
        "a": Decimal("0"),
        "b": Decimal("0"),
        "c": Decimal("0"),
        "d": Decimal("0"),
        "z": Decimal("0"),
        "index_value_A": None,
        "index_value_B": None,
        "index_value_C": None,
        "index_value_D": None,
        "source_sheet": "Vast",
        "source_row": 2,
    }

def make_parsed(
    source_rows: tuple[int, ...],
    sheet_name: str = "Vast",
) -> ParsedVTestWorkbook:
    return ParsedVTestWorkbook(
        source_path=Path("vtest.xlsx"),
        fixed=pd.DataFrame(),
        variable_dynamic=pd.DataFrame(),
        sheets=(
            ParsedSheet(
                sheet_name=sheet_name,
                header_row=0,
                rows=len(source_rows),
                columns=(),
                source_rows=source_rows,
            ),
        ),
        warnings=(),
    )

def test_accepts_valid_fixed_row():
    report = VTestDataValidator().validate(
        parsed=make_parsed((2,)),
        fixed=pd.DataFrame([make_row()]),
        variable_dynamic=pd.DataFrame(),
    )
    assert report.valid
    assert report.errors == ()

def test_warns_duplicate_component():
    first_row = make_row()

    second_row = make_row()
    second_row["source_row"] = 3

    report = VTestDataValidator().validate(
        parsed=make_parsed((2, 3)),
        fixed=pd.DataFrame(
            [
                first_row,
                second_row,
            ]
        ),
        variable_dynamic=pd.DataFrame(),
    )

    assert report.valid

    assert any(
        issue.code == "duplicate_component"
        for issue in report.warnings
    )

    assert not any(
        issue.code == "duplicate_source_row"
        for issue in report.errors
    )

def test_rejects_fixed_row_without_price():
    row = make_row()
    row["price"] = None
    report = VTestDataValidator().validate(
        parsed=make_parsed((2,)),
        fixed=pd.DataFrame([row]),
        variable_dynamic=pd.DataFrame(),
    )
    assert not report.valid
    assert any(issue.code == "fixed_price_missing" for issue in report.errors)

def test_accepts_variable_formula_without_price():
    row = make_row()
    row["product_type"] = "variabel"
    row["price"] = None
    row["a"] = Decimal("0.11")
    row["index_value_A"] = Decimal("85.31")
    report = VTestDataValidator().validate(
        parsed=make_parsed((2,)),
        fixed=pd.DataFrame(),
        variable_dynamic=pd.DataFrame([row]),
    )
    assert report.valid

def test_warns_for_missing_index_value():
    row = make_row()
    row["product_type"] = "variabel"
    row["price"] = None
    row["a"] = Decimal("0.11")
    report = VTestDataValidator().validate(
        parsed=make_parsed((2,)),
        fixed=pd.DataFrame(),
        variable_dynamic=pd.DataFrame([row]),
    )
    assert report.valid
    assert any(issue.code == "index_value_missing" for issue in report.warnings)

def test_rejects_variable_without_price_or_formula():
    row = make_row()
    row["product_type"] = "variabel"
    row["price"] = None
    report = VTestDataValidator().validate(
        parsed=make_parsed((2,)),
        fixed=pd.DataFrame(),
        variable_dynamic=pd.DataFrame([row]),
    )
    assert not report.valid
    assert any(issue.code == "variable_price_missing" for issue in report.errors)

def test_source_coverage_passes_for_complete_output() -> None:
    parsed = make_parsed(
        (2, 3, 4),
        sheet_name="Testblad",
    )

    fixed = pd.DataFrame(
        {
            "source_sheet": [
                "Testblad",
                "Testblad",
            ],
            "source_row": [2, 3],
        }
    )

    variable_dynamic = pd.DataFrame(
        {
            "source_sheet": ["Testblad"],
            "source_row": [4],
        }
    )

    issues = VTestDataValidator._validate_source_coverage(
        parsed=parsed,
        fixed=fixed,
        variable_dynamic=variable_dynamic,
    )

    assert issues == []

def test_source_coverage_detects_missing_row() -> None:
    parsed = make_parsed(
        (2, 3, 4),
        sheet_name="Testblad",
    )

    fixed = pd.DataFrame(
        {
            "source_sheet": ["Testblad"],
            "source_row": [2],
        }
    )

    variable_dynamic = pd.DataFrame(
        {
            "source_sheet": ["Testblad"],
            "source_row": [4],
        }
    )

    issues = VTestDataValidator._validate_source_coverage(
        parsed=parsed,
        fixed=fixed,
        variable_dynamic=variable_dynamic,
    )

    assert any(
        issue.code == "missing_source_row"
        and issue.source_sheet == "Testblad"
        and issue.source_row == 3
        for issue in issues
    )

def test_source_coverage_detects_duplicate_row() -> None:
    parsed = make_parsed(
        (2, 3),
        sheet_name="Testblad",
    )

    fixed = pd.DataFrame(
        {
            "source_sheet": [
                "Testblad",
                "Testblad",
                "Testblad",
            ],
            "source_row": [2, 2, 3],
        }
    )

    issues = VTestDataValidator._validate_source_coverage(
        parsed=parsed,
        fixed=fixed,
        variable_dynamic=pd.DataFrame(),
    )

    assert any(
        issue.code == "duplicate_source_row"
        and issue.source_row == 2
        for issue in issues
    )

def test_source_coverage_detects_row_in_both_tables() -> None:
    parsed = make_parsed(
        (2,),
        sheet_name="Testblad",
    )

    fixed = pd.DataFrame(
        {
            "source_sheet": ["Testblad"],
            "source_row": [2],
        }
    )

    variable_dynamic = pd.DataFrame(
        {
            "source_sheet": ["Testblad"],
            "source_row": [2],
        }
    )

    issues = VTestDataValidator._validate_source_coverage(
        parsed=parsed,
        fixed=fixed,
        variable_dynamic=variable_dynamic,
    )

    codes = {issue.code for issue in issues}

    assert "duplicate_source_row" in codes
    assert "source_row_in_both_tables" in codes

def test_validate_rejects_mismatching_source_sheet() -> None:
    row = make_row()

    report = VTestDataValidator().validate(
        parsed=make_parsed(
            (2,),
            sheet_name="Ander blad",
        ),
        fixed=pd.DataFrame([row]),
        variable_dynamic=pd.DataFrame(),
    )

    error_codes = {
        issue.code
        for issue in report.errors
    }

    assert "missing_source_row" in error_codes
    assert "unexpected_source_row" in error_codes
    assert not report.valid