from __future__ import annotations
import logging
from dataclasses import dataclass
from pathlib import Path
import pandas as pd
from energie_vlaanderen.utility.normalizer import clean_text, nullify

LOG = logging.getLogger(__name__)

class TariffWorkbookError(RuntimeError):
    pass

SKIP_SHEET_MARKERS = frozenset({"Overzicht", "Per DNB"})

# Header staat normaal op Excel-rij 5 (0-indexed 4), behalve bij de "* ELEK
# Injectie"-sheets: daar staat de échte kop op Excel-rij 3 (0-indexed 2). Met
# header=4 werd voor die sheets de eerste datarij ("Tarief voor het
# netgebruik") als kop verbruikt en zo stil weggegooid.
HEADER_ROW_DEFAULT = 4          # Excel rij 5 — Afname-sheets, GAS Injectie
HEADER_ROW_ELEK_INJECTIE = 2    # Excel rij 3 — enkel "* ELEK Injectie"

@dataclass(frozen=True)
class ParsedTariffSheet:
    sheet_name: str
    rows: int
    columns: tuple[str, ...]
    source_rows: tuple[int, ...]

@dataclass(frozen=True)
class ParsedTariffWorkbook:
    source_path: Path
    afname: pd.DataFrame
    injectie: pd.DataFrame
    sheets: tuple[ParsedTariffSheet, ...]
    warnings: tuple[str, ...]

class TariffWorkbookParser:
    def parse(self, path: Path, energy_type: str = "electricity") -> ParsedTariffWorkbook:
        source_path = path.expanduser().resolve()
        if not source_path.is_file():
            raise TariffWorkbookError(f"Tarievenwerkboek bestaat niet: {source_path}")

        sheet_filter = "ELEK" if energy_type == "electricity" else "GAS"
        workbook = pd.ExcelFile(source_path, engine="openpyxl")

        afname_frames: list[pd.DataFrame] = []
        injectie_frames: list[pd.DataFrame] = []
        parsed_sheets: list[ParsedTariffSheet] = []
        warnings: list[str] = []

        for sheet_name in workbook.sheet_names:
            if sheet_filter not in sheet_name or any(m in sheet_name for m in SKIP_SHEET_MARKERS):
                continue

            is_elek_injectie = "ELEK" in sheet_name and "Injectie" in sheet_name
            header_row = HEADER_ROW_ELEK_INJECTIE if is_elek_injectie else HEADER_ROW_DEFAULT

            frame = pd.read_excel(source_path, sheet_name=sheet_name, header=header_row, dtype=object, engine="openpyxl")
            frame = frame.dropna(how="all").copy()

            if frame.empty:
                warnings.append(f"Werkblad {sheet_name!r} bevat geen data.")
                continue

            frame["source_sheet"] = sheet_name
            # DataFrame index 0 correspondeert met de Excel-rij net na de header
            # (Excel-rijnummer = header_row + 2, 1-indexed: header op rij header_row+1).
            frame["source_row"] = frame.index + header_row + 2

            parsed_sheets.append(ParsedTariffSheet(
                sheet_name=sheet_name,
                rows=len(frame),
                columns=tuple(frame.columns),
                source_rows=tuple(int(v) for v in frame["source_row"].tolist()),
            ))

            if "Afname" in sheet_name:
                afname_frames.append(frame)
            elif "Injectie" in sheet_name:
                injectie_frames.append(frame)

        afname_result = pd.concat(afname_frames, ignore_index=True) if afname_frames else pd.DataFrame()
        injectie_result = pd.concat(injectie_frames, ignore_index=True) if injectie_frames else pd.DataFrame()

        return ParsedTariffWorkbook(
            source_path=source_path,
            afname=afname_result,
            injectie=injectie_result,
            sheets=tuple(parsed_sheets),
            warnings=tuple(warnings),
        )
