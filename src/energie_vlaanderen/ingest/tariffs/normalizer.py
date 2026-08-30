from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import pandas as pd
from energie_vlaanderen.utility.normalizer import clean_text

class TariffNormalizationError(RuntimeError):
    pass

DNB_MAPPING = {
    "FA": "FA", "FHV": "FHV", "FI": "FI", "FK": "FK",
    "FL": "FL", "FMV": "FMV", "FW": "FW", "FZD": "FZD"
}

# Gas afname: (column_index, klanttype_label)
GAS_AFNAME_COLS = [
    (3, "GAS_T1"),
    (4, "GAS_T2"),
    (5, "GAS_T3"),
    (6, "GAS_T4"),
    (7, "GAS_T5"),
    (8, "GAS_T6"),
    (9, "GAS_LD"),
    (10, "GAS_MD"),
]

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

        out = []
        current_hoofdgroep = ""

        for _, row in frame.iterrows():
            source_sheet = clean_text(row.get("source_sheet", ""))
            dnb_code = source_sheet.split(" ")[0] if source_sheet else ""
            dnb_mapped = DNB_MAPPING.get(dnb_code)

            if not dnb_mapped:
                continue

            source_row_raw = row.get("source_row")
            try:
                source_row: int | None = int(source_row_raw) if source_row_raw is not None and pd.notna(source_row_raw) else None
            except (ValueError, TypeError):
                source_row = None

            is_gas = "GAS" in source_sheet

            col0 = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
            desc = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ""

            if col0.isdigit() and len(col0) == 1:
                current_hoofdgroep = desc.split(" *")[0].strip()

            if not desc and current_hoofdgroep:
                desc = current_hoofdgroep

            desc = desc.split(" *")[0].strip()

            # Rijen waarvan de omschrijving met "- " of "*" begint zijn voetnoten
            # in de Excel-bron — geen echte tariefregels.
            if desc.startswith("- ") or desc.startswith("*"):
                continue

            base_data = {
                "Netbeheerder": dnb_mapped,
                "Contracttype": direction,
                "Tarieftype": current_hoofdgroep,
                "Tariefdetail": desc,
                "source_sheet": source_sheet,
                "source_row": source_row,
            }

            if direction == "Afname":
                if is_gas:
                    if len(row) > 10:
                        unit = str(row.iloc[2]).strip() if pd.notna(row.iloc[2]) else ""
                        for col_idx, klanttype in GAS_AFNAME_COLS:
                            val = self._safe_price(row.iloc[col_idx])
                            if val is not None:
                                out.append({**base_data, "Tariefnotering": unit, "Klanttype": klanttype, "Prijs_num": val})
                else:
                    if len(row) > 15:
                        unit = str(row.iloc[3]).strip() if pd.notna(row.iloc[3]) else ""
                        val_digi = self._safe_price(row.iloc[13])
                        val_ana = self._safe_price(row.iloc[14])
                        val_pro = self._safe_price(row.iloc[15])

                        if val_digi is not None:
                            out.append({**base_data, "Tariefnotering": unit, "Klanttype": "ELEK_LS_DIGI", "Prijs_num": val_digi})
                        if val_ana is not None:
                            out.append({**base_data, "Tariefnotering": unit, "Klanttype": "ELEK_LS_ANA", "Prijs_num": val_ana})
                        if val_pro is not None:
                            out.append({**base_data, "Tariefnotering": unit, "Klanttype": "ELEK_LS_ANA_PRO", "Prijs_num": val_pro})

            elif direction == "Injectie":
                if is_gas:
                    if len(row) > 3:
                        val = self._safe_price(row.iloc[3])
                        unit = str(row.iloc[2]).strip() if pd.notna(row.iloc[2]) else ""
                        if val is not None:
                            out.append({**base_data, "Tariefnotering": unit, "Klanttype": "GAS_INJ", "Prijs_num": val})
                else:
                    if len(row) > 4:
                        val = self._safe_price(row.iloc[3])
                        unit = str(row.iloc[4]).strip() if pd.notna(row.iloc[4]) else ""
                        if val is not None:
                            out.append({**base_data, "Tariefnotering": unit, "Klanttype": "ELEK_LS_DIGI", "Prijs_num": val})

        return pd.DataFrame(out) if out else pd.DataFrame()

    @staticmethod
    def _safe_price(val: Any) -> float | None:
        try:
            if pd.isna(val) or str(val).strip() == "":
                return None
            return float(val)
        except (ValueError, TypeError):
            return None
