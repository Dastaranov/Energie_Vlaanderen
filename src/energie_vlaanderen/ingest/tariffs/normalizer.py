from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import pandas as pd
from energie_vlaanderen.utility.constants import DNB_CODES
from energie_vlaanderen.utility.normalizer import clean_text

class TariffNormalizationError(RuntimeError):
    pass

# Geldige DNB-afkortingen zoals ze als prefix in werkbladnamen voorkomen
# (bv. "FA ELEK Afname" -> "FA"). Afgeleid van DNB_CODES (utility/constants.py)
# zodat deze whitelist en de netbeheerder-tabel nooit uit elkaar groeien.
VALID_DNB_ABBREVIATIONS = frozenset(DNB_CODES.values())

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

# Elektriciteit afname: (column_index, klanttype_label). Kolommen 7, 10, 12
# zijn altijd-lege scheidingskolommen in de bron en komen hier niet in voor.
ELEK_AFNAME_COLS = [
    (5, "ELEK_HS1"),
    (6, "ELEK_HS2"),
    (8, "ELEK_MS1"),
    (9, "ELEK_MS2"),
    (11, "ELEK_LS_DC"),
    (13, "ELEK_LS_DIGI"),
    (14, "ELEK_LS_ANA"),
    (15, "ELEK_LS_ANA_PRO"),
]

# Elektriciteit injectie: Tariefdetail-tekst -> klanttypes waarop de prijs van
# toepassing is (fan-out). Eerste match wint.
ELEK_INJECTIE_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("Tarief voor het netgebruik", (
        "ELEK_HS1", "ELEK_HS2", "ELEK_MS1", "ELEK_MS2", "ELEK_LS_DC",
        "ELEK_LS_DIGI", "ELEK_LS_ANA", "ELEK_LS_ANA_PRO",
    )),
    ("26-36 kV, 1-26 kV, distributiecabine", (
        "ELEK_HS1", "ELEK_HS2", "ELEK_MS1", "ELEK_MS2", "ELEK_LS_DC",
    )),
    ("Laagspanningnet", (
        "ELEK_LS_DIGI", "ELEK_LS_ANA", "ELEK_LS_ANA_PRO",
    )),
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
            dnb_mapped = dnb_code if dnb_code in VALID_DNB_ABBREVIATIONS else None

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
                        for col_idx, klanttype in ELEK_AFNAME_COLS:
                            val = self._safe_price(row.iloc[col_idx])
                            if val is not None:
                                out.append({**base_data, "Tariefnotering": unit, "Klanttype": klanttype, "Prijs_num": val})

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
                            klanttypes = self._match_elek_injectie_klanttypes(desc)
                            if klanttypes:
                                for klanttype in klanttypes:
                                    out.append({**base_data, "Tariefnotering": unit, "Klanttype": klanttype, "Prijs_num": val})
                            else:
                                issues.append(RowIssue(
                                    source_sheet=source_sheet,
                                    severity="warning",
                                    message=(
                                        f"Injectietarief {desc!r} (rij {source_row}) komt niet overeen "
                                        "met een bekende klanttype-groep en werd niet geëxporteerd."
                                    ),
                                ))

        return pd.DataFrame(out) if out else pd.DataFrame()

    @staticmethod
    def _match_elek_injectie_klanttypes(desc: str) -> tuple[str, ...]:
        for needle, klanttypes in ELEK_INJECTIE_GROUPS:
            if needle in desc:
                return klanttypes
        return ()

    @staticmethod
    def _safe_price(val: Any) -> float | None:
        try:
            if pd.isna(val) or str(val).strip() == "":
                return None
            return float(val)
        except (ValueError, TypeError):
            return None
