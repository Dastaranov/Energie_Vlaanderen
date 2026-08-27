from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
import pandas as pd
from energie_vlaanderen.utility.normalizer import clean_text, dec

class TariffNormalizationError(RuntimeError):
    pass

# Hier vertalen we de afkortingen uit de tabbladnamen
DNB_MAPPING = {
    "FA": "Fluvius Antwerpen",
    "FHV": "Fluvius Halle-Vilvoorde",
    "FI": "Fluvius Imewo",
    "FK": "Fluvius Kempen",
    "FL": "Fluvius Limburg",
    "FMV": "Fluvius Midden-Vlaanderen",
    "FW": "Fluvius West",
    "FZD": "Fluvius Zenne-Dijle"
}

@dataclass(frozen=True)
class RowIssue:
    source_sheet: str
    severity: str
    message: str

@dataclass(frozen=True)
class NormalizedTariffData:
    afname: pd.DataFrame
    injectie: pd.DataFrame
    issues: tuple[RowIssue, ...]

    @property
    def errors(self) -> tuple[RowIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "error")

    @property
    def warnings(self) -> tuple[RowIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "warning")

class TariffDataNormalizer:
    def normalize(self, afname: pd.DataFrame, injectie: pd.DataFrame) -> NormalizedTariffData:
        issues: list[RowIssue] = []

        norm_afname = self._normalize_frame(afname, direction="Afname", issues=issues)
        norm_injectie = self._normalize_frame(injectie, direction="Injectie", issues=issues)

        return NormalizedTariffData(afname=norm_afname, injectie=norm_injectie, issues=tuple(issues))

    def _normalize_frame(self, frame: pd.DataFrame, direction: str, issues: list[RowIssue]) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame()

        rows: list[dict[str, Any]] = []
        for _, source_row in frame.iterrows():
            normalized = self._normalize_row(source_row, direction, issues)
            if normalized is not None:
                rows.append(normalized)

        return pd.DataFrame(rows) if rows else pd.DataFrame()

    def _normalize_row(self, row: pd.Series, direction: str, issues: list[RowIssue]) -> dict[str, Any] | None:
        source_sheet = clean_text(row.get("source_sheet"))
        
        # Haal de DNB code uit de sheetnaam (bijv "FA ELEK Afname" -> "FA")
        dnb_code = source_sheet.split(" ")[0] if source_sheet else ""
        dnb_name = DNB_MAPPING.get(dnb_code, "Onbekende DNB")

        # Voorbeeld: We halen de omschrijving en prijs op. 
        # (Let op: dit moet afgestemd worden op de exacte kolommen van de Excel)
        omschrijving = clean_text(row.iloc[0]) # Eerste kolom is vaak de omschrijving
        
        if not omschrijving:
            return None # Lege rijen negeren we
            
        return {
            "dnb": dnb_name,
            "direction": direction,
            "omschrijving": omschrijving,
            "source_sheet": source_sheet,
            # Hier voegen we later de exacte logica toe om de eenheden (EUR/kW/jaar etc) en prijzen (dec) te koppelen
        }