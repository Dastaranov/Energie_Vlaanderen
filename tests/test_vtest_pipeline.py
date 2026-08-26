from __future__ import annotations
from decimal import Decimal

import json
from pathlib import Path

import pandas as pd
import pytest

from src.energie_vlaanderen.ingest.vtest.pipeline import VTestPipeline, VTestPipelineError


def write_workbook(path: Path, price: str = "30,50") -> None:
    fixed = pd.DataFrame(
        [
            {
                "Jaar": 2026,
                "Maand": "aug",
                "Segment": "Woning",
                "Energietype": "Elektriciteit",
                "Contracttype": "Afname",
                "Handelsnaam": "Leverancier A",
                "Productnaam": "Product Vast",
                "Vast/variabel/dynamisch": "Vast",
                "Prijsonderdeel": "Enkelvoudige meter dagtarief",
                "Prijs": price,
            }
        ]
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        fixed.to_excel(writer, sheet_name="Vast", index=False)


def test_pipeline_writes_normalized_output(tmp_path: Path):
    workbook = tmp_path / "vtest.xlsx"
    write_workbook(workbook)

    result = VTestPipeline().process(
        source_path=workbook,
        destination=tmp_path / "staging",
        version_id="20260820T120000Z-1234abcd",
    )

    assert result.fixed_rows == 1
    assert result.variable_dynamic_rows == 0
    assert result.fixed_csv.is_file()
    assert result.variable_dynamic_csv.is_file()
    assert result.report_json.is_file()

    fixed = pd.read_csv(
        result.fixed_csv,
        sep=";",
        dtype=str,
        encoding="utf-8-sig",
    )

    price = Decimal(
        fixed.loc[0, "price"].replace(",", ".")
    )

    assert price == Decimal("30.50")
    assert fixed.loc[0, "product_type"] == "vast"
    assert fixed.loc[0, "component"] == "single"

    report = json.loads(result.report_json.read_text(encoding="utf-8"))
    assert report["fixed_rows"] == 1
    assert report["variable_dynamic_rows"] == 0


def test_pipeline_refuses_invalid_data(tmp_path: Path):
    workbook = tmp_path / "vtest.xlsx"
    write_workbook(workbook, price="(Empty)")
    staging = tmp_path / "staging"

    with pytest.raises(VTestPipelineError, match="blokkerende fouten"):
        VTestPipeline().process(
            source_path=workbook,
            destination=staging,
            version_id="20260820T120000Z-1234abcd",
        )

    assert not (staging / "vtest").exists()


def test_pipeline_refuses_existing_target(tmp_path: Path):
    workbook = tmp_path / "vtest.xlsx"
    write_workbook(workbook)
    destination = tmp_path / "staging"
    (destination / "vtest").mkdir(parents=True)

    with pytest.raises(VTestPipelineError, match="bestaat al"):
        VTestPipeline().process(
            source_path=workbook,
            destination=destination,
            version_id="20260820T120000Z-1234abcd",
        )

def test_csv_value_preserves_decimal_precision():
    value = Decimal("1.9710771")

    result = VTestPipeline._csv_value(value)

    assert result == "1,9710771"
