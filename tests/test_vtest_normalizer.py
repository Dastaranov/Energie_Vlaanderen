from __future__ import annotations

from decimal import Decimal

import pandas as pd

from energie_vlaanderen.ingest.vtest.normalizer import (
    VTestDataNormalizer,
)


def make_fixed_row() -> dict[str, object]:
    return {
        "Jaar": 2026,
        "Maand": "jun",
        "Segment": "Woning",
        "Energietype": "Elektriciteit",
        "Contracttype": "Afname",
        "Handelsnaam": "Leverancier A",
        "Productnaam": "Product Vast",
        "Vast/variabel/dynamisch": "Vast",
        "Prijsonderdeel": (
            "Enkelvoudige meter dagtarief"
        ),
        "Prijs": "1.234,56",
        "source_sheet": "Vast",
        "source_row": 2,
    }


def make_variable_row() -> dict[str, object]:
    return {
        "Jaar": "2026",
        "Maand": "aug",
        "Segment": "Woning",
        "Energietype": "Elektriciteit",
        "Contracttype": "Afname",
        "Handelsnaam": "Leverancier B",
        "Productnaam": "Product Variabel",
        "Variabel/Dynamisch": "Variabel",
        "Prijsonderdeel": (
            "Enkelvoudige meter dagtarief"
        ),
        "Prijs": "(Empty)",
        "a": "0,11",
        "b": "0",
        "c": "0",
        "d": "0",
        "z": "1,51",
        "Indexatieparameter A": "EPEX",
        "Waarde A (€/MWh)": "85,31",
        "source_sheet": "Variabel",
        "source_row": 3,
    }


def test_normalizes_fixed_decimal():
    fixed = pd.DataFrame(
        [make_fixed_row()]
    )

    result = VTestDataNormalizer().normalize(
        fixed,
        pd.DataFrame(),
    )

    assert len(result.fixed) == 1
    assert result.fixed.loc[0, "year"] == 2026
    assert result.fixed.loc[0, "month"] == 6
    assert result.fixed.loc[0, "product_type"] == "vast"
    assert result.fixed.loc[0, "component"] == "single"

    assert (
        result.fixed.loc[0, "price"]
        == Decimal("1234.56")
    )

    assert result.errors == ()


def test_normalizes_variable_formula():
    variable = pd.DataFrame(
        [make_variable_row()]
    )

    result = VTestDataNormalizer().normalize(
        pd.DataFrame(),
        variable,
    )

    frame = result.variable_dynamic

    assert len(frame) == 1
    assert frame.loc[0, "month"] == 8
    assert frame.loc[0, "product_type"] == "variabel"
    assert frame.loc[0, "price"] is None
    assert frame.loc[0, "a"] == Decimal("0.11")
    assert frame.loc[0, "z"] == Decimal("1.51")

    assert (
        frame.loc[0, "index_value_A"]
        == Decimal("85.31")
    )

    assert frame.loc[0, "index_name_A"] == "EPEX"


def test_rejects_unknown_segment():
    row = make_fixed_row()
    row["Segment"] = "Onbekend"

    result = VTestDataNormalizer().normalize(
        pd.DataFrame([row]),
        pd.DataFrame(),
    )

    assert result.fixed.empty
    assert len(result.errors) == 1
    assert "Segment" in result.errors[0].message


def test_warns_for_missing_index_value():
    row = make_variable_row()
    row["Waarde A (€/MWh)"] = "(Empty)"

    result = VTestDataNormalizer().normalize(
        pd.DataFrame(),
        pd.DataFrame([row]),
    )

    assert len(result.variable_dynamic) == 1

    assert any(
        "indexwaarde A" in issue.message
        for issue in result.warnings
    )


def test_rejects_product_in_wrong_table():
    row = make_fixed_row()
    row["Vast/variabel/dynamisch"] = "Variabel"

    result = VTestDataNormalizer().normalize(
        pd.DataFrame([row]),
        pd.DataFrame(),
    )

    assert result.fixed.empty

    assert any(
        "verkeerde tabel" in issue.message
        for issue in result.errors
    )
