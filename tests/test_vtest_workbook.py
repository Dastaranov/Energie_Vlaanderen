"""De bladindeling van het V-test-werkboek.

VREG wisselt kop-rijen, bladnamen en taal tussen jaargangen. Wat hier vastligt is
hoe een blad herkend wordt en wanneer het genegeerd hoort te worden; op een vaste
index lezen zou data aan de verkeerde kolom hangen zonder dat er iets faalt.
"""
from __future__ import annotations

from pathlib import Path
from unittest import result
from unittest import result

import pandas as pd
import pytest

from src.energie_vlaanderen.ingest.vtest.workbook import (
    VTestWorkbookError,
    VTestWorkbookParser,
)


BASE_COLUMNS = [
    "Jaar",
    "Maand",
    "Segment",
    "Energietype",
    "Contracttype",
    "Handelsnaam",
    "Productnaam",
    "Prijsonderdeel",
]


pytestmark = pytest.mark.parsers


def write_sheet_with_title(
    writer: pd.ExcelWriter,
    sheet_name: str,
    frame: pd.DataFrame,
    title_rows: int = 2,
) -> None:
    title_values = [
        ["V-test productdata"],
        ["Prijzen exclusief btw"],
    ]

    title = pd.DataFrame(
        title_values[:title_rows]
    )

    title.to_excel(
        writer,
        sheet_name=sheet_name,
        header=False,
        index=False,
    )

    frame.to_excel(
        writer,
        sheet_name=sheet_name,
        startrow=title_rows,
        index=False,
    )


def fixed_product_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Jaar": 2026,
                "Maand": "aug",
                "Segment": "Woning",
                "Energietype": "Elektriciteit",
                "Contracttype": "Afname",
                "Handelsnaam": "Leverancier A",
                "Productnaam": "Vast Product",
                "Vast/variabel/dynamisch": "Vast",
                "Prijsonderdeel": (
                    "Enkelvoudige meter dagtarief"
                ),
                "Prijs": "30,50",
            }
        ]
    )


def variable_product_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Jaar": 2026,
                "Maand": "aug",
                "Segment": "Woning",
                "Energietype": "Elektriciteit",
                "Contracttype": "Afname",
                "Handelsnaam": "Leverancier B",
                "Productnaam": "Variabel Product",
                "Variabel/Dynamisch": "Variabel",
                "Prijsonderdeel": (
                    "Enkelvoudige meter dagtarief"
                ),
                "Prijs": "25,10",
            },
            {
                "Jaar": 2026,
                "Maand": "aug",
                "Segment": "Woning",
                "Energietype": "Elektriciteit",
                "Contracttype": "Afname",
                "Handelsnaam": "Leverancier C",
                "Productnaam": "Dynamisch Product",
                "Variabel/Dynamisch": "Dynamisch",
                "Prijsonderdeel": "Dynamisch tarief",
                "Prijs": "0,00",
            },
        ]
    )

def test_parser_finds_fixed_and_variable_sheets(
    tmp_path: Path,
):
    workbook = tmp_path / "vtest.xlsx"

    fixed = fixed_product_frame()
    variable = variable_product_frame()

    fixed_sheet_name = "Vaste producten"
    variable_sheet_name = "Variabele en dynamische prod."

    # Excel ondersteunt maximaal 31 tekens per werkbladnaam.
    assert len(fixed_sheet_name) <= 31
    assert len(variable_sheet_name) <= 31

    with pd.ExcelWriter(
        workbook,
        engine="openpyxl",
    ) as writer:
        write_sheet_with_title(
            writer,
            fixed_sheet_name,
            fixed,
        )

        write_sheet_with_title(
            writer,
            variable_sheet_name,
            variable,
        )

    parsed = VTestWorkbookParser().parse(workbook)

    assert parsed.source_path == workbook.resolve()
    assert parsed.fixed_rows == 1
    assert parsed.variable_dynamic_rows == 2
    assert len(parsed.sheets) == 2
    assert parsed.warnings == ()

    assert (
        parsed.fixed.loc[
            0,
            "Productnaam",
        ]
        == "Vast Product"
    )

    assert set(
        parsed.variable_dynamic["Productnaam"]
    ) == {
        "Variabel Product",
        "Dynamisch Product",
    }

    assert "source_sheet" in parsed.fixed.columns
    assert "source_row" in parsed.fixed.columns

    assert (
        parsed.fixed.loc[
            0,
            "source_sheet",
        ]
        == fixed_sheet_name
    )

    assert (
        parsed.fixed.loc[
            0,
            "source_row",
        ]
        == 4
    )

    assert (
        parsed.variable_dynamic.loc[
            0,
            "source_sheet",
        ]
        == variable_sheet_name
    )

def test_parser_can_classify_by_sheet_name(
    tmp_path: Path,
):
    workbook = tmp_path / "vtest.xlsx"

    frame = pd.DataFrame(
        [
            {
                "Jaar": 2026,
                "Maand": "aug",
                "Segment": "Woning",
                "Energietype": "Gas",
                "Contracttype": "Afname",
                "Handelsnaam": "Leverancier",
                "Productnaam": "Gas Vast",
                "Prijsonderdeel": (
                    "Enkelvoudige meter dagtarief"
                ),
                "Prijs": "7,50",
            }
        ],
        columns=(
            BASE_COLUMNS
            + ["Prijs"]
        ),
    )

    with pd.ExcelWriter(
        workbook,
        engine="openpyxl",
    ) as writer:
        write_sheet_with_title(
            writer,
            "Vast",
            frame,
        )

    parsed = VTestWorkbookParser().parse(
        workbook
    )

    assert parsed.fixed_rows == 1
    assert parsed.variable_dynamic_rows == 0

    assert (
        parsed.fixed.loc[
            0,
            "Productnaam",
        ]
        == "Gas Vast"
    )

    assert any(
        "Geen variabele of dynamische" in warning
        for warning in parsed.warnings
    )

def test_parser_ignores_non_product_sheet(
    tmp_path: Path,
):
    workbook = tmp_path / "vtest.xlsx"

    products = fixed_product_frame()

    notes = pd.DataFrame(
        {
            "Opmerking": [
                "Dit is geen producttabel."
            ]
        }
    )

    with pd.ExcelWriter(
        workbook,
        engine="openpyxl",
    ) as writer:
        write_sheet_with_title(
            writer,
            "Vaste producten",
            products,
        )

        notes.to_excel(
            writer,
            sheet_name="Toelichting",
            index=False,
        )

    parsed = VTestWorkbookParser().parse(
        workbook
    )

    assert parsed.fixed_rows == 1
    assert parsed.variable_dynamic_rows == 0
    assert len(parsed.sheets) == 1

    assert (
        parsed.sheets[0].sheet_name
        == "Vaste producten"
    )

def test_parser_rejects_workbook_without_products(
    tmp_path: Path,
):
    workbook_path = (
        tmp_path
        / "vtest_zonder_producten.xlsx"
    )

    with pd.ExcelWriter(
        workbook_path,
        engine="openpyxl",
    ) as writer:
        pd.DataFrame(
            {
                "Opmerking": [
                    "Dit werkboek bevat geen productgegevens."
                ],
                "Waarde": [
                    "Geen bruikbare V-test-rijen."
                ],
            }
        ).to_excel(
            writer,
            sheet_name="Informatie",
            index=False,
        )

    parser = VTestWorkbookParser()

    with pytest.raises(
        VTestWorkbookError,
        match="Geen enkel werkblad",
    ):
        parser.parse(workbook_path)

def test_parser_rejects_missing_workbook(
    tmp_path: Path,
):
    workbook_path = (
        tmp_path
        / "ontbrekend_vtest_bestand.xlsx"
    )

    parser = VTestWorkbookParser()

    with pytest.raises(
        VTestWorkbookError,
        match="bestaat niet",
    ):
        parser.parse(workbook_path)

def test_parser_skips_empty_sheets(
    tmp_path: Path,
):
    workbook_path = (
        tmp_path
        / "vtest_met_leeg_blad.xlsx"
    )

    product_data = pd.DataFrame(
        {
            "Jaar": [2026],
            "Maand": ["jun"],
            "Segment": ["Woning"],
            "Energietype": ["Elektriciteit"],
            "Contracttype": ["Afname"],
            "Handelsnaam": ["Leverancier A"],
            "Productnaam": ["Product X"],
            "Vast/variabel/dynamisch": ["Vast"],
            "Prijsonderdeel": [
                "Enkelvoudige meter dagtarief"
            ],
            "Prijs": ["25,50"],
        }
    )

    with pd.ExcelWriter(
        workbook_path,
        engine="openpyxl",
    ) as writer:
        pd.DataFrame().to_excel(
            writer,
            sheet_name="Leeg",
            index=False,
        )

        product_data.to_excel(
            writer,
            sheet_name="Vaste producten",
            index=False,
        )

    parser = VTestWorkbookParser()
    result = parser.parse(workbook_path)

    assert result.fixed_rows == 1
    assert result.variable_dynamic_rows == 0
    assert not result.fixed.empty
    assert len(result.fixed) == 1

    assert (
        result.fixed.iloc[0]["Handelsnaam"]
        == "Leverancier A"
    )

    assert (
        result.fixed.iloc[0]["Productnaam"]
        == "Product X"
    )

def test_parser_preserves_source_metadata(
    tmp_path: Path,
):
    workbook_path = (
        tmp_path
        / "vtest_metadata.xlsx"
    )

    product_data = pd.DataFrame(
        {
            "Jaar": [2026],
            "Maand": ["jun"],
            "Segment": ["Woning"],
            "Energietype": ["Elektriciteit"],
            "Contracttype": ["Afname"],
            "Handelsnaam": ["Leverancier B"],
            "Productnaam": ["Product Y"],
            "Vast/variabel/dynamisch": ["Variabel"],
            "Prijsonderdeel": [
                "Enkelvoudige meter dagtarief"
            ],
            "Prijs": ["27,25"],
        }
    )

    with pd.ExcelWriter(
        workbook_path,
        engine="openpyxl",
    ) as writer:
        product_data.to_excel(
            writer,
            sheet_name="Variabele producten",
            index=False,
        )

    parser = VTestWorkbookParser()
    result = parser.parse(workbook_path)

    frame = result.variable_dynamic

    assert not frame.empty
    assert len(frame) == 1
    assert "source_sheet" in frame.columns
    assert "source_row" in frame.columns
    assert frame.loc[0, "source_sheet"] == "Variabele producten"
    assert frame.loc[0, "source_row"] == 2

    # 1. We controleren het bronbestand direct
    assert result.source_path == workbook_path

    # 2. We halen de verwerkte tabbladen rechtstreeks uit het resultaat
    parsed_sheets = result.sheets
 
    # 3. We pakken het eerste (en enige) tabblad uit de lijst en controleren de naam
    assert parsed_sheets[0].sheet_name == "Variabele producten"

def test_parser_normalizes_empty_values(
    tmp_path: Path,
):
    workbook_path = (
        tmp_path
        / "vtest_lege_waarden.xlsx"
    )

    product_data = pd.DataFrame(
        {
            "Jaar": [2026],
            "Maand": ["jun"],
            "Segment": ["Woning"],
            "Energietype": ["Elektriciteit"],
            "Contracttype": ["Afname"],
            "Handelsnaam": ["Leverancier C"],
            "Productnaam": ["Product Z"],
            "Vast/variabel/dynamisch": ["Variabel"],
            "Prijsonderdeel": [
                "Enkelvoudige meter dagtarief"
            ],
            "Prijs": ["(Empty)"],
            "Indexatieparameter A": ["(Empty)"],
        }
    )

    with pd.ExcelWriter(
        workbook_path,
        engine="openpyxl",
    ) as writer:
        product_data.to_excel(
            writer,
            sheet_name="Producten",
            index=False,
        )

    parser = VTestWorkbookParser()
    result = parser.parse(workbook_path)

    frame = result.variable_dynamic

    assert len(frame) == 1

    assert pd.isna(
        frame.iloc[0]["Prijs"]
    )

    assert pd.isna(
        frame.iloc[0]["Indexatieparameter A"]
    )

def test_parser_handles_belgian_decimal_values(
    tmp_path: Path,
):
    workbook_path = (
        tmp_path
        / "vtest_decimalen.xlsx"
    )

    product_data = pd.DataFrame(
        {
            "Jaar": [2026],
            "Maand": ["jun"],
            "Segment": ["Woning"],
            "Energietype": ["Elektriciteit"],
            "Contracttype": ["Afname"],
            "Handelsnaam": ["Leverancier D"],
            "Productnaam": ["Product Decimal"],
            "Vast/variabel/dynamisch": ["Vast"],
            "Prijsonderdeel": [
                "Enkelvoudige meter dagtarief"
            ],
            "Prijs": ["1.234,56"],
        }
    )

    with pd.ExcelWriter(
        workbook_path,
        engine="openpyxl",
    ) as writer:
        product_data.to_excel(
            writer,
            sheet_name="Producten",
            index=False,
        )

    parser = VTestWorkbookParser()
    result = parser.parse(workbook_path)

    frame = result.fixed
    assert len(frame) == 1

    assert str(frame.iloc[0]["Prijs"]) == "1.234,56"

def test_summary_detection_requires_consistent_markers():
    row = pd.Series(
        {
            "Handelsnaam": "Echte leverancier",
            "Productnaam": "Subtotal voordeel",
            "Vast/variabel/dynamisch": "Vast",
            "Prijsonderdeel": (
                "Enkelvoudige meter dagtarief "
                "(c€/kWh)"
            ),
        }
    )

    assert not VTestWorkbookParser.is_summary_row(
        row
    )

def test_detects_vnr_subtotal_format():
    row = pd.Series(
        {
            "Handelsnaam": "Subtotal",
            "Productnaam": "Subtotal",
            "Vast/variabel/dynamisch": "Subtotal",
            "Prijsonderdeel": "Subtotal",
        }
    )

    assert VTestWorkbookParser.is_summary_row(
        row
    )


def test_parser_recognizes_english_year_month_headers(
    tmp_path: Path,
):
    """Regressietest voor de stille dataverlies-bug: een werkblad dat
    'Year'/'Month' i.p.v. 'Jaar'/'Maand' gebruikt (zoals het echte
    "Var-dyn (excl. btw) (2026)"-tabblad) moet nog steeds herkend worden."""
    workbook_path = tmp_path / "vtest_engelse_koppen.xlsx"

    product_data = pd.DataFrame(
        {
            "Year": [2026],
            "Month": ["jan"],
            "Segment": ["Onderneming"],
            "Energietype": ["Elektriciteit"],
            "Contracttype": ["Afname"],
            "Handelsnaam": ["Leverancier E"],
            "Productnaam": ["Variabel Product 2026"],
            "Variabel/Dynamisch": ["Variabel"],
            "Prijsonderdeel": [
                "Enkelvoudige meter dagtarief"
            ],
            "Prijs": ["16,18"],
        }
    )

    with pd.ExcelWriter(
        workbook_path,
        engine="openpyxl",
    ) as writer:
        product_data.to_excel(
            writer,
            sheet_name="Var-dyn (excl. btw) (2026)",
            index=False,
        )

    parser = VTestWorkbookParser()
    result = parser.parse(workbook_path)

    assert result.variable_dynamic_rows == 1
    assert result.fixed_rows == 0

    frame = result.variable_dynamic
    assert "Jaar" in frame.columns
    assert "Maand" in frame.columns
    assert "Year" not in frame.columns
    assert "Month" not in frame.columns
    assert str(frame.loc[0, "Jaar"]) == "2026"
    assert frame.loc[0, "Maand"] == "jan"


def test_parser_matches_real_var_dyn_2026_header_shape(
    tmp_path: Path,
):
    """Nabootsing van de échte kolomstructuur van
    'Var-dyn (excl. btw) (2026)' (Engelse Year/Month, index-kolommen A/B/C/D/z
    met 'VNR waarde'), naast het reeds correct verwerkte
    'Vast (excl. btw) (2026)'-tabblad met Nederlandse koppen."""
    workbook_path = tmp_path / "vtest_2026.xlsx"

    var_dyn_data = pd.DataFrame(
        {
            "Year": [2026],
            "Month": ["jan"],
            "Segment": ["Onderneming"],
            "Energietype": ["Elektriciteit"],
            "Contracttype": ["Afname"],
            "Handelsnaam": ["Belvus"],
            "Productnaam": ["Flex Online Pro EL"],
            "Variabel/Dynamisch": ["Variabel"],
            "Prijsonderdeel": ["Enkelvoudige meter dagtarief"],
            "Indexatieparameter A (a.A+b.B+c.C+d.D+z)": ["A"],
            "Beschrijving A": ["Maandgemiddelde"],
            "Waarde A (€/MWh) - VNR waarde": ["45,00"],
            "Waarde A (€/MWh) - laatst gekende waarde": ["45,00"],
            "a": ["1"],
            "b": ["0"],
            "c": ["0"],
            "d": ["0"],
            "z": ["0"],
            "Prijs": ["16,18"],
        }
    )

    vast_data = pd.DataFrame(
        {
            "Jaar": [2026],
            "Maand": ["jan"],
            "Segment": ["Onderneming"],
            "Energietype": ["Elektriciteit"],
            "Contracttype": ["Afname"],
            "Handelsnaam": ["Bolt"],
            "Productnaam": ["Bolt Vast"],
            "Vast/variabel/dynamisch": ["Vast"],
            "Prijsonderdeel": ["Enkelvoudige meter dagtarief"],
            "Prijs": ["16,18"],
        }
    )

    with pd.ExcelWriter(
        workbook_path,
        engine="openpyxl",
    ) as writer:
        var_dyn_data.to_excel(
            writer,
            sheet_name="Var-dyn (excl. btw) (2026)",
            index=False,
        )
        vast_data.to_excel(
            writer,
            sheet_name="Vast (excl. btw) (2026)",
            index=False,
        )

    parser = VTestWorkbookParser()
    result = parser.parse(workbook_path)

    sheet_names = {sheet.sheet_name for sheet in result.sheets}
    assert "Var-dyn (excl. btw) (2026)" in sheet_names
    assert "Vast (excl. btw) (2026)" in sheet_names

    assert result.variable_dynamic_rows > 0
    assert result.fixed_rows > 0


def test_parser_raises_when_year_suffixed_sheet_header_not_found(
    tmp_path: Path,
):
    """Als een tabblad met een jaartal in de naam geen herkenbare
    producttabel-header bevat, moet dit hard falen i.p.v. stil worden
    overgeslagen (silent-data-loss-bescherming)."""
    workbook_path = tmp_path / "vtest_onherkenbaar_2099.xlsx"

    unrelated = pd.DataFrame(
        {
            "Foo": ["a"],
            "Bar": ["b"],
        }
    )

    with pd.ExcelWriter(
        workbook_path,
        engine="openpyxl",
    ) as writer:
        unrelated.to_excel(
            writer,
            sheet_name="Var-dyn (excl. btw) (2099)",
            index=False,
        )

    parser = VTestWorkbookParser()

    with pytest.raises(
        VTestWorkbookError,
        match="jaargebonden",
    ):
        parser.parse(workbook_path)