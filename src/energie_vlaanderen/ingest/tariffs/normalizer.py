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

            # Kolom 0 is in deze sheets vaak de groepsnummering (bijv. "1", "2")
            col0 = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
            # Kolom 1 bevat de tekst (bijv. "Tarieven voor het netgebruik *1")
            desc = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ""

            # Detecteer een nieuwe hoofdgroep
            if col0.isdigit() and len(col0) == 1:
                current_hoofdgroep = desc.split(" *")[0].strip()
            
            # Vul ontbrekende omschrijvingen op met de naam van de hoofdgroep
            if not desc and current_hoofdgroep:
                desc = current_hoofdgroep
            
            # Poets de sterretjes (voetnoten) weg uit de beschrijving
            desc = desc.split(" *")[0].strip()

            base_data = {
                "Netbeheerder": dnb_mapped,
                "Contracttype": direction,
                "Tarieftype": current_hoofdgroep,
                "Tariefdetail": desc,
            }

            if direction == "Afname":
                # Afname heeft 15+ kolommen. Eenheid = col 3, Prijzen = col 13, 14, 15
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
                # Injectie heeft 5 kolommen. Prijs = col 3, Eenheid = col 4
                if len(row) > 4:
                    val = self._safe_price(row.iloc[3])
                    unit = str(row.iloc[4]).strip() if pd.notna(row.iloc[4]) else ""
                    
                    if val is not None:
                        # Injectietarief is enkel voor digitale meters
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