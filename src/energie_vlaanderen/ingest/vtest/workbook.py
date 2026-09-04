from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from energie_vlaanderen.utility.normalizer import clean_text, nullify

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


# Sommige (nieuwere) werkbladen gebruiken Engelse koppen voor Jaar/Maand
# (bv. "Var-dyn (excl. btw) (2026)") terwijl de rest van het werkblad
# Nederlands is. Alias ze naar de Nederlandse kolomnaam zodat
# REQUIRED_PRODUCT_COLUMNS ze nog steeds herkent — analoog aan hoe
# _uses_legacy_index_schema de X/Y/Z-vs-A/B/C/D-variatie opvangt.
COLUMN_ALIASES: dict[str, str] = {
    "year": "Jaar",
    "month": "Maand",
}

# Werkbladnamen die op een jaartal eindigen (bv. "... (2026)") zijn
# vermoedelijk jaargebonden producttabellen. Als voor zo'n werkblad geen
# geldige header gevonden wordt, is dat een teken van een gewijzigd
# kolomformaat (stille dataverlies-bug) en geen onschuldig niet-productblad.
SHEET_YEAR_SUFFIX_RE = re.compile(r"\(\d{4}\)\s*$")


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
    source_rows: tuple[int, ...]


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
                if SHEET_YEAR_SUFFIX_RE.search(sheet_name):
                    raise VTestWorkbookError(
                        f"Werkblad {sheet_name!r} lijkt een jaargebonden "
                        "producttabel (naam eindigt op een jaartal), maar "
                        "de verplichte kolommen "
                        f"({', '.join(sorted(REQUIRED_PRODUCT_COLUMNS))}) "
                        "konden niet worden gevonden binnen de eerste "
                        f"{self.max_header_rows} rijen. Controleer of het "
                        "kolomformaat van dit werkblad gewijzigd is (bv. "
                        "nieuwe Engelse kolomnamen) en werk COLUMN_ALIASES "
                        "bij indien nodig."
                    )
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
                    source_rows=tuple(
                        int(value)
                        for value in frame[
                            "source_row"
                        ].tolist()
                    ),
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
                self._alias_column(clean_text(value))
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

    @staticmethod
    def _alias_column(name: str) -> str:
        """Vertaal een (mogelijk Engelse) kolomnaam naar zijn canonieke
        Nederlandse variant, zie COLUMN_ALIASES. Onbekende namen worden
        ongewijzigd teruggegeven."""
        return COLUMN_ALIASES.get(name.casefold(), name)

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
                self._alias_column(clean_text(column))
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

        summary_mask = frame.apply(
            self.is_summary_row,
            axis=1,
        )

        summary_rows = frame.loc[
            summary_mask,
            "source_row",
        ].astype(int).tolist()

        if summary_rows:
            LOG.info(
                "Werkblad %s: %d samenvattingsrijen "
                "genegeerd: %s",
                sheet_name,
                len(summary_rows),
                summary_rows[:20],
            )

        frame = frame.loc[
            ~summary_mask
        ].copy()

        frame = frame.reset_index(
            drop=True
        )

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


    SUMMARY_MARKERS = frozenset(
        {
            "subtotal",
            "subtotaal",
            "total",
            "totaal",
            "grand total",
            "eindtotaal",
        }
    )


    @classmethod
    def is_summary_row(
        cls,
        row: pd.Series,
    ) -> bool:
        identifying_columns = (
            "Handelsnaam",
            "Productnaam",
            "Vast/variabel/dynamisch",
            "Prijsonderdeel",
        )

        values = {
            clean_text(row.get(column)).casefold()
            for column in identifying_columns
            if clean_text(row.get(column))
        }

        if not values:
            return False

        return values.issubset(
            cls.SUMMARY_MARKERS
        )