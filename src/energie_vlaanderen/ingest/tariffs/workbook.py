from __future__ import annotations
import logging
from dataclasses import dataclass
from pathlib import Path
import pandas as pd
from energie_vlaanderen.utility.normalizer import clean_text, nullify

LOG = logging.getLogger(__name__)

class TariffWorkbookError(RuntimeError):
    pass

# Pas deze aan naar de kolomkoppen die we echt nodig hebben in de tarieven
REQUIRED_TARIFF_COLUMNS = frozenset({"Laagspanningsnet", "Tarieven voor het netgebruik"})

@dataclass(frozen=True)
class ParsedTariffSheet:
    sheet_name: str
    rows: int
    columns: tuple[str, ...]

@dataclass(frozen=True)
class ParsedTariffWorkbook:
    source_path: Path
    afname: pd.DataFrame
    injectie: pd.DataFrame
    sheets: tuple[ParsedTariffSheet, ...]
    warnings: tuple[str, ...]

class TariffWorkbookParser:
    def parse(self, path: Path) -> ParsedTariffWorkbook:
        source_path = path.expanduser().resolve()
        if not source_path.is_file():
            raise TariffWorkbookError(f"Tarievenwerkboek bestaat niet: {source_path}")

        workbook = pd.ExcelFile(source_path, engine="openpyxl")
        
        afname_frames: list[pd.DataFrame] = []
        injectie_frames: list[pd.DataFrame] = []
        parsed_sheets: list[ParsedTariffSheet] = []
        warnings: list[str] = []

        for sheet_name in workbook.sheet_names:
            # We filteren overzichtsbladen weg, we willen enkel de ruwe DNB data
            if "ELEK" not in sheet_name or "Overzicht" in sheet_name:
                continue
                
            # Voor tarieven slaan we grofweg de eerste 3-4 rijen over (logo's en titels)
            frame = pd.read_excel(source_path, sheet_name=sheet_name, header=4, dtype=object, engine="openpyxl")
            frame = frame.dropna(how="all").copy()
            
            if frame.empty:
                warnings.append(f"Werkblad {sheet_name!r} bevat geen data.")
                continue

            # Voeg bronvermelding toe
            frame["source_sheet"] = sheet_name
            
            parsed_sheets.append(ParsedTariffSheet(sheet_name=sheet_name, rows=len(frame), columns=tuple(frame.columns)))

            # Splits op basis van de naam van het tabblad
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