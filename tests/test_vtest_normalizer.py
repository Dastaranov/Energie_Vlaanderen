from __future__ import annotations

from decimal import Decimal

import pandas as pd

from energie_vlaanderen.ingest.vtest.normalizer import (
    VTestDataNormalizer,
)
from energie_vlaanderen.ingest.vtest.validator import VTestDataValidator


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

def test_errors_for_missing_index_value():
    row = make_variable_row()
    row["Waarde A (€/MWh)"] = "(Empty)"

    result = VTestDataNormalizer().normalize(
        pd.DataFrame(),
        pd.DataFrame([row]),
    )

    assert len(result.variable_dynamic) == 1

    assert any(
        "indexwaarde A" in issue.message
        for issue in result.errors
    ), result.issues

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

def test_detects_legacy_index_schema() -> None:
    row = pd.Series(
        {
            "Indexatieparameter X (a.X + b.Y + c.Z + d)": "Index X",
            "Indexatieparameter Y (a.X + b.Y + c.Z + d)": "Index Y",
            "Indexatieparameter Z (a.X + b.Y + c.Z + d)": "Index Z",
            "a": 1,
            "b": 2,
            "c": 3,
            "d": 4,
        }
    )

    result = VTestDataNormalizer._uses_legacy_index_schema(row)

    assert result is True

def test_detects_new_index_schema() -> None:
    row = pd.Series(
        {
            "Indexatieparameter A (a.A + b.B + c.C + d.D + z)": "Index A",
            "Indexatieparameter B (a.A + b.B + c.C + d.D + z)": "Index B",
            "Indexatieparameter C (a.A + b.B + c.C + d.D + z)": "Index C",
            "Indexatieparameter D (a.A + b.B + c.C + d.D + z)": "Index D",
            "a": 1,
            "b": 2,
            "c": 3,
            "d": 4,
            "z": 5,
        }
    )

    result = VTestDataNormalizer._uses_legacy_index_schema(row)

    assert result is False

def test_maps_legacy_constant_d_to_z() -> None:
    row = pd.Series(
        {
            "Indexatieparameter X (a.X + b.Y + c.Z + d)": "Index X",
            "a": "0,129",
            "b": "0",
            "c": "0",
            "d": "0,407",
        }
    )

    result = VTestDataNormalizer._coefficients(row)

    assert result == {
        "a": Decimal("0.129"),
        "b": Decimal("0"),
        "c": Decimal("0"),
        "d": Decimal("0"),
        "z": Decimal("0.407"),
    }

def test_preserves_new_d_and_z() -> None:
    row = pd.Series(
        {
            "Indexatieparameter A (a.A + b.B + c.C + d.D + z)": "Index A",
            "Indexatieparameter D (a.A + b.B + c.C + d.D + z)": "Index D",
            "a": "0,1",
            "b": "0,2",
            "c": "0,3",
            "d": "0,4",
            "z": "0,5",
        }
    )

    result = VTestDataNormalizer._coefficients(row)

    assert result == {
        "a": Decimal("0.1"),
        "b": Decimal("0.2"),
        "c": Decimal("0.3"),
        "d": Decimal("0.4"),
        "z": Decimal("0.5"),
    }

def test_maps_single_meter_fixed_fee() -> None:
    result = VTestDataNormalizer._component_key(
        "Vaste vergoeding enkelvoudige meter (€)"
    )

    assert result == "fixed_fee_single"

def test_maps_double_meter_fixed_fee() -> None:
    result = VTestDataNormalizer._component_key(
        "Vaste vergoeding tweevoudige meter (€)"
    )

    assert result == "fixed_fee_double"

def test_maps_exclusive_night_fixed_fee() -> None:
    result = VTestDataNormalizer._component_key(
        "Vaste vergoeding uitsluitend nachtmeter (€)"
    )

    assert result == (
        "fixed_fee_exclusive_night"
    )

def test_maps_exclusive_night_fixed_fee() -> None:
    result = VTestDataNormalizer._component_key(
        "Vaste vergoeding uitsluitend nachtmeter (€)"
    )

    assert result == (
        "fixed_fee_exclusive_night"
    )

def test_maps_general_fixed_fee() -> None:
    result = VTestDataNormalizer._component_key(
        "Vaste vergoeding (€)"
    )

    assert result == "fixed_fee"

def test_meter_specific_fixed_fees_are_not_duplicates():
    frame = pd.DataFrame(
        [
            {
                "year": 2025,
                "month": 1,
                "segment": "Woning",
                "energy": "Elektriciteit",
                "direction": "Afname",
                "supplier": "Ebem",
                "product": "EBEM Groen B@sic+",
                "product_type": "variabel",
                "component": "fixed_fee_single",
                "component_label": (
                    "Vaste vergoeding "
                    "enkelvoudige meter (€)"
                ),
                "price": Decimal("70.75"),
                "source_sheet": "Producten var-dyn",
                "source_row": 1861,
            },
            {
                "year": 2025,
                "month": 1,
                "segment": "Woning",
                "energy": "Elektriciteit",
                "direction": "Afname",
                "supplier": "Ebem",
                "product": "EBEM Groen B@sic+",
                "product_type": "variabel",
                "component": "fixed_fee_double",
                "component_label": (
                    "Vaste vergoeding "
                    "tweevoudige meter (€)"
                ),
                "price": Decimal("70.75"),
                "source_sheet": "Producten var-dyn",
                "source_row": 1862,
            },
            {
                "year": 2025,
                "month": 1,
                "segment": "Woning",
                "energy": "Elektriciteit",
                "direction": "Afname",
                "supplier": "Ebem",
                "product": "EBEM Groen B@sic+",
                "product_type": "variabel",
                "component": (
                    "fixed_fee_exclusive_night"
                ),
                "component_label": (
                    "Vaste vergoeding "
                    "uitsluitend nachtmeter (€)"
                ),
                "price": Decimal("33.06"),
                "source_sheet": "Producten var-dyn",
                "source_row": 1863,
            },
        ]
    )

    duplicates = frame.duplicated(
        subset=list(
            VTestDataValidator.KEY_COLUMNS
        ),
        keep=False,
    )

    assert not duplicates.any()