from decimal import Decimal
from pathlib import Path

import pandas as pd

from energie_vlaanderen.ingest.vtest.pipeline import VTestPipeline
from energie_vlaanderen.ingest.vtest.validator import VTestDataValidator
from energie_vlaanderen.ingest.vtest.workbook import (
    ParsedSheet,
    ParsedVTestWorkbook,
)


def test_csv_value_preserves_decimal_text() -> None:
    assert (
        VTestPipeline._csv_value(
            Decimal("0.123400")
        )
        == "0,123400"
    )


def test_zero_price_is_not_missing() -> None:
    fixed = pd.DataFrame(
        [
            {
                "year": 2026,
                "month": 8,
                "segment": "Woning",
                "energy": "Elektriciteit",
                "direction": "Afname",
                "supplier": "Test",
                "product": "Zero",
                "product_type": "vast",
                "component": "single",
                "component_label": (
                    "Enkelvoudige meter dagtarief "
                    "(c€/kWh)"
                ),
                "price": Decimal("0"),
                "a": Decimal("0"),
                "b": Decimal("0"),
                "c": Decimal("0"),
                "d": Decimal("0"),
                "z": Decimal("0"),
                "source_sheet": "Vast",
                "source_row": 2,
            }
        ]
    )

    parsed = ParsedVTestWorkbook(
        source_path=Path("vtest.xlsx"),
        fixed=pd.DataFrame(),
        variable_dynamic=pd.DataFrame(),
        sheets=(
            ParsedSheet(
                sheet_name="Vast",
                header_row=0,
                rows=1,
                columns=tuple(),
                source_rows=(2,),
            ),
        ),
        warnings=tuple(),
    )

    report = VTestDataValidator().validate(
        parsed,
        fixed,
        pd.DataFrame(),
    )

    assert report.valid, report.issues