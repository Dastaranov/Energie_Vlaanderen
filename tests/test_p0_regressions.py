from decimal import Decimal
from pathlib import Path

import pandas as pd

from src.energie_vlaanderen.ingest.vtest.pipeline import VTestPipeline
from src.energie_vlaanderen.ingest.vtest.validator import VTestDataValidator


def test_csv_value_preserves_decimal_text() -> None:
    assert VTestPipeline._csv_value(Decimal("0.123400")) == "0,123400"


def test_zero_price_is_not_missing() -> None:
    validator = VTestDataValidator()
    frame = pd.DataFrame([{
        "year": 2026, "month": 8, "segment": "Woning",
        "energy": "Elektriciteit", "direction": "Afname",
        "supplier": "Test", "product": "Zero",
        "product_type": "vast", "component": "single",
        "price": Decimal("0"), "source_sheet": "Vast", "source_row": 2,
    }])
    report = validator.validate(frame, pd.DataFrame())
    assert report.valid
