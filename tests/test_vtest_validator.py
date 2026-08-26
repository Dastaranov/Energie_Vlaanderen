from __future__ import annotations

from decimal import Decimal

import pandas as pd

from src.energie_vlaanderen.ingest.vtest.validator import VTestDataValidator


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


def test_accepts_valid_fixed_row():
    report = VTestDataValidator().validate(pd.DataFrame([make_row()]), pd.DataFrame())
    assert report.valid
    assert report.errors == ()


def test_rejects_duplicate_component():
    row = make_row()
    report = VTestDataValidator().validate(
        pd.DataFrame([row, row.copy()]), pd.DataFrame()
    )
    assert not report.valid
    assert any(issue.code == "duplicate_component" for issue in report.errors)


def test_rejects_fixed_row_without_price():
    row = make_row()
    row["price"] = None
    report = VTestDataValidator().validate(pd.DataFrame([row]), pd.DataFrame())
    assert not report.valid
    assert any(issue.code == "fixed_price_missing" for issue in report.errors)


def test_accepts_variable_formula_without_price():
    row = make_row()
    row["product_type"] = "variabel"
    row["price"] = None
    row["a"] = Decimal("0.11")
    row["index_value_A"] = Decimal("85.31")
    report = VTestDataValidator().validate(pd.DataFrame(), pd.DataFrame([row]))
    assert report.valid


def test_warns_for_missing_index_value():
    row = make_row()
    row["product_type"] = "variabel"
    row["price"] = None
    row["a"] = Decimal("0.11")
    report = VTestDataValidator().validate(pd.DataFrame(), pd.DataFrame([row]))
    assert report.valid
    assert any(issue.code == "index_value_missing" for issue in report.warnings)


def test_rejects_variable_without_price_or_formula():
    row = make_row()
    row["product_type"] = "variabel"
    row["price"] = None
    report = VTestDataValidator().validate(pd.DataFrame(), pd.DataFrame([row]))
    assert not report.valid
    assert any(issue.code == "variable_price_missing" for issue in report.errors)
