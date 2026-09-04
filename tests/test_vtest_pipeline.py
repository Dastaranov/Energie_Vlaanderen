"""De bulkexport van werkboek tot CSV, in één keer.

De pipeline weigert liever dan half te slagen: ongeldige data gaat er niet door,
een bestaand doel wordt niet overschreven, en een fout in het werkboek komt naar
buiten als een pipelinefout in plaats van een traceback. De precisietest hoort
hier omdat dit de laatste stap is waar een decimaal nog verloren kan gaan.
"""
from __future__ import annotations
from decimal import Decimal

import json
from pathlib import Path

import pandas as pd
import pytest

from energie_vlaanderen.ingest.vtest.pipeline import VTestPipeline, VTestPipelineError


pytestmark = pytest.mark.parsers


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
    """Bestaande parse-output wordt niet stilzwijgend overschreven.

    De vtest-map zelf mag wél al bestaan: `staging refine` zet zijn
    scrape-resultaten daar neer en die moeten een herparse overleven.
    """
    workbook = tmp_path / "vtest.xlsx"
    write_workbook(workbook)
    destination = tmp_path / "staging"
    (destination / "vtest").mkdir(parents=True)
    (destination / "vtest" / "master_vast.csv").write_text("", encoding="utf-8")

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


def test_pipeline_parses_var_dyn_sheet_with_english_year_month_headers(
    tmp_path: Path,
):
    """Regressietest voor de stille dataverlies-bug: het echte
    'Var-dyn (excl. btw) (2026)'-tabblad gebruikt 'Year'/'Month' i.p.v.
    'Jaar'/'Maand' en moet toch in master_var_dyn.csv terechtkomen."""
    workbook = tmp_path / "vtest.xlsx"

    variable = pd.DataFrame(
        [
            {
                "Year": 2026,
                "Month": "jan",
                "Segment": "Onderneming",
                "Energietype": "Elektriciteit",
                "Contracttype": "Afname",
                "Handelsnaam": "Belvus",
                "Productnaam": "Flex Online Pro EL",
                "Variabel/Dynamisch": "Variabel",
                "Prijsonderdeel": "Enkelvoudige meter dagtarief",
                "Prijs": "16,18",
            }
        ]
    )

    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        variable.to_excel(
            writer,
            sheet_name="Var-dyn (excl. btw) (2026)",
            index=False,
        )

    result = VTestPipeline().process(
        source_path=workbook,
        destination=tmp_path / "staging",
        version_id="20260820T120000Z-1234abcd",
    )

    assert result.variable_dynamic_rows == 1
    assert result.fixed_rows == 0

    report = json.loads(result.report_json.read_text(encoding="utf-8"))
    assert report["variable_dynamic_rows"] == 1
    assert any(
        sheet["sheet_name"] == "Var-dyn (excl. btw) (2026)"
        for sheet in report["sheets"]
    )


def test_pipeline_wraps_workbook_error_as_pipeline_error(tmp_path: Path):
    """Een jaartal-gesuffixt tabblad zonder herkenbare header moet als
    VTestPipelineError naar buiten komen (niet de ruwe VTestWorkbookError),
    zodat de CLI dit als verwachte fout (exit code 2) kan afhandelen."""
    workbook = tmp_path / "vtest.xlsx"

    unrelated = pd.DataFrame({"Foo": ["a"], "Bar": ["b"]})

    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        unrelated.to_excel(
            writer,
            sheet_name="Var-dyn (excl. btw) (2099)",
            index=False,
        )

    with pytest.raises(VTestPipelineError, match="jaargebonden"):
        VTestPipeline().process(
            source_path=workbook,
            destination=tmp_path / "staging",
            version_id="20260820T120000Z-1234abcd",
        )


def test_pipeline_schrijft_in_een_map_met_scrape_resultaten(tmp_path: Path):
    """Een herparse mag de refine-output naast zich laten staan.

    Voorheen weigerde de pipeline zodra de vtest-map bestond, terwijl de
    aanroeper de parse-output er al uit verwijderd had — met als gevolg dat
    master_vast.csv en master_var_dyn.csv verdwenen zonder vervanging.
    """
    workbook = tmp_path / "vtest.xlsx"
    write_workbook(workbook)
    destination = tmp_path / "staging"
    vtest_dir = destination / "vtest"
    vtest_dir.mkdir(parents=True)
    scrape_output = vtest_dir / "vtest_products_woning_elektriciteit_9120.csv"
    scrape_output.write_text("vreg_id;segment\n1;woning\n", encoding="utf-8")

    result = VTestPipeline().process(workbook, destination, "v1")

    assert result.fixed_csv.is_file()
    assert result.variable_dynamic_csv.is_file()
    assert scrape_output.read_text(encoding="utf-8").startswith("vreg_id")
