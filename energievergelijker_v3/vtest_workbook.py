from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .normalizer import clean_text, nullify


LOG = logging.getLogger(__name__)


class VTestWorkbookError(RuntimeError):
    pass


REQUIRED_PRODUCT_COLUMNS = frozenset(
    {
        "Jaar",
        "Maand",
        "Segment",
        "Energietype",
        "Contracttype",
        "Handelsnaam",
        "Productnaam",
        "Prijsonderdeel",
    }
)


TYPE_COLUMN_CANDIDATES = (
    "Vast/variabel/dynamisch",
    "Variabel/Dynamisch",
    "Contractformule",
    "Producttype",
)


@dataclass(frozen=True)
class ParsedSheet:
    sheet_name: str
    header_row: int
    rows: int
    columns: tuple[str, ...]


@dataclass(frozen=True)
class ParsedVTestWorkbook:
    source_path: Path
    fixed: pd.DataFrame
    variable_dynamic: pd.DataFrame
    sheets: tuple[ParsedSheet, ...]
    warnings: tuple[str, ...]

    @property
    def fixed_rows(self) -> int:
        return len(self.fixed)

    @property
    def variable_dynamic_rows(self) -> int:
        return len(self.variable_dynamic)


class VTestWorkbookParser:
    def __init__(
        self,
        max_header_rows: int = 50,
    ):
        if max_header_rows <= 0:
            raise ValueError(
                "max_header_rows moet groter zijn dan nul."
            )

        self.max_header_rows = max_header_rows

    def parse(
        self,
        path: Path,
    ) -> ParsedVTestWorkbook:
        source_path = path.expanduser().resolve()

        if not source_path.is_file():
            raise VTestWorkbookError(
                f"V-testwerkboek bestaat niet: {source_path}"
            )

        try:
            workbook = pd.ExcelFile(
                source_path,
                engine="openpyxl",
            )
        except Exception as exc:
            raise VTestWorkbookError(
                f"V-testwerkboek kan niet worden geopend: "
                f"{source_path}: {exc}"
            ) from exc

        fixed_frames: list[pd.DataFrame] = []
        variable_frames: list[pd.DataFrame] = []
        parsed_sheets: list[ParsedSheet] = []
        warnings: list[str] = []

        for sheet_name in workbook.sheet_names:
            header_row = self.find_header_row(
                source_path,
                sheet_name,
            )

            if header_row is None:
                LOG.debug(
                    "Werkblad %s bevat geen producttabel.",
                    sheet_name,
                )
                continue

            frame = self.read_product_sheet(
                source_path,
                sheet_name,
                header_row,
            )

            if frame.empty:
                warnings.append(
                    f"Werkblad {sheet_name!r} bevat "
                    "een header maar geen productrijen."
                )
                continue

            parsed_sheets.append(
                ParsedSheet(
                    sheet_name=sheet_name,
                    header_row=header_row,
                    rows=len(frame),
                    columns=tuple(frame.columns),
                )
            )

            fixed, variable_dynamic = (
                self.split_contract_types(
                    frame,
                    sheet_name,
                )
            )

            if not fixed.empty:
                fixed_frames.append(fixed)

            if not variable_dynamic.empty:
                variable_frames.append(
                    variable_dynamic
                )

            classified = (
                len(fixed)
                + len(variable_dynamic)
            )

            if classified < len(frame):
                warnings.append(
                    f"Werkblad {sheet_name!r}: "
                    f"{len(frame) - classified} rijen "
                    "konden niet als vast, variabel "
                    "of dynamisch worden geclassificeerd."
                )

        if not parsed_sheets:
            raise VTestWorkbookError(
                "Geen enkel werkblad bevat de vereiste "
                "V-testproductkolommen."
            )

        fixed_result = self.combine_frames(
            fixed_frames
        )

        variable_result = self.combine_frames(
            variable_frames
        )

        if fixed_result.empty:
            warnings.append(
                "Geen vaste producten gevonden."
            )

        if variable_result.empty:
            warnings.append(
                "Geen variabele of dynamische "
                "producten gevonden."
            )

        return ParsedVTestWorkbook(
            source_path=source_path,
            fixed=fixed_result,
            variable_dynamic=variable_result,
            sheets=tuple(parsed_sheets),
            warnings=tuple(warnings),
        )

    def find_header_row(
        self,
        path: Path,
        sheet_name: str,
    ) -> int | None:
        try:
            preview = pd.read_excel(
                path,
                sheet_name=sheet_name,
                header=None,
                nrows=self.max_header_rows,
                dtype=object,
                engine="openpyxl",
            )
        except Exception as exc:
            raise VTestWorkbookError(
                f"Werkblad {sheet_name!r} kan "
                f"niet worden gelezen: {exc}"
            ) from exc

        for row_number in range(len(preview)):
            values = {
                clean_text(value)
                for value in preview.iloc[
                    row_number
                ].tolist()
                if clean_text(value)
            }

            if REQUIRED_PRODUCT_COLUMNS.issubset(
                values
            ):
                return row_number

        return None

    def read_product_sheet(
        self,
        path: Path,
        sheet_name: str,
        header_row: int,
    ) -> pd.DataFrame:
        try:
            frame = pd.read_excel(
                path,
                sheet_name=sheet_name,
                header=header_row,
                dtype=object,
                engine="openpyxl",
            )
        except Exception as exc:
            raise VTestWorkbookError(
                f"Producttabel uit werkblad "
                f"{sheet_name!r} kan niet worden "
                f"gelezen: {exc}"
            ) from exc

        frame.columns = self.unique_columns(
            [
                clean_text(column)
                for column in frame.columns
            ]
        )

        missing = (
            REQUIRED_PRODUCT_COLUMNS
            - set(frame.columns)
        )

        if missing:
            raise VTestWorkbookError(
                f"Werkblad {sheet_name!r} mist "
                "verplichte kolommen: "
                + ", ".join(sorted(missing))
            )

        for column in frame.columns:
            frame[column] = frame[column].map(
                nullify
            )

        frame = frame.dropna(
            how="all"
        ).copy()

        if frame.empty:
            return frame

        relevant_columns = [
            "Jaar",
            "Maand",
            "Handelsnaam",
            "Productnaam",
            "Prijsonderdeel",
        ]

        frame = frame.dropna(
            subset=relevant_columns,
            how="all",
        ).copy()

        frame["source_sheet"] = sheet_name

        frame["source_row"] = (
            frame.index
            + header_row
            + 2
        )

        frame = frame.reset_index(
            drop=True
        )

        # Bewaar bronwaarden ongewijzigd. Financiele conversie naar Decimal
        # gebeurt uitsluitend in VTestDataNormalizer via normalizer.dec().
        return frame

    def split_contract_types(
        self,
        frame: pd.DataFrame,
        sheet_name: str,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        type_column = self.find_type_column(
            frame
        )

        if type_column is not None:
            type_values = (
                frame[type_column]
                .fillna("")
                .map(clean_text)
                .str.casefold()
            )

            fixed_mask = type_values.str.contains(
                "vast",
                regex=False,
            )

            variable_mask = (
                type_values.str.contains(
                    "variabel",
                    regex=False,
                )
                | type_values.str.contains(
                    "dynamisch",
                    regex=False,
                )
            )

            fixed = frame.loc[
                fixed_mask
            ].copy()

            variable_dynamic = frame.loc[
                variable_mask
            ].copy()

            return fixed, variable_dynamic

        sheet_label = clean_text(
            sheet_name
        ).casefold()

        if (
            "variabel" in sheet_label
            or "dynamisch" in sheet_label
        ):
            return (
                self.empty_like(frame),
                frame.copy(),
            )

        if "vast" in sheet_label:
            return (
                frame.copy(),
                self.empty_like(frame),
            )

        raise VTestWorkbookError(
            f"Werkblad {sheet_name!r} bevat geen "
            "herkenbare producttypekolom en de "
            "werkbladnaam vermeldt niet vast, "
            "variabel of dynamisch."
        )

    @staticmethod
    def find_type_column(
        frame: pd.DataFrame,
    ) -> str | None:
        folded = {
            clean_text(column).casefold(): column
            for column in frame.columns
        }

        for candidate in TYPE_COLUMN_CANDIDATES:
            match = folded.get(
                candidate.casefold()
            )

            if match is not None:
                return match

        return None

    @staticmethod
    def combine_frames(
        frames: list[pd.DataFrame],
    ) -> pd.DataFrame:
        if not frames:
            return pd.DataFrame()

        result = pd.concat(
            frames,
            ignore_index=True,
            sort=False,
        )

        return result.reset_index(
            drop=True
        )

    @staticmethod
    def empty_like(
        frame: pd.DataFrame,
    ) -> pd.DataFrame:
        return frame.iloc[0:0].copy()

    @staticmethod
    def unique_columns(
        columns: list[str],
    ) -> list[str]:
        result: list[str] = []
        counts: dict[str, int] = {}

        for column in columns:
            base = column or "Unnamed"
            key = base.casefold()

            counts[key] = (
                counts.get(key, 0)
                + 1
            )

            if counts[key] == 1:
                result.append(base)
            else:
                result.append(
                    f"{base}__{counts[key]}"
                )

        return result