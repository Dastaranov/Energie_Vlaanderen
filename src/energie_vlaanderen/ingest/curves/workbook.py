from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

LOG = logging.getLogger(__name__)


class CurvesWorkbookError(RuntimeError):
    pass


@dataclass(frozen=True)
class ParsedCurvesWorkbook:
    source_path: Path
    timeseries: pd.DataFrame
    spot: pd.DataFrame
    forward: pd.DataFrame


class CurvesWorkbookParser:
    def parse(self, path: Path) -> ParsedCurvesWorkbook:
        source_path = path.expanduser().resolve()
        if not source_path.is_file():
            raise CurvesWorkbookError(f"Curves werkboek bestaat niet: {source_path}")

        try:
            workbook = pd.ExcelFile(source_path, engine="openpyxl")
        except Exception as exc:
            raise CurvesWorkbookError(f"Curves werkboek kan niet geopend worden: {exc}") from exc

        ts_rows = []
        spot_rows = []
        fwd_rows = []

        for sheet in workbook.sheet_names:
            name_upper = sheet.upper()
            if "SPOT" in name_upper:
                spot_rows.extend(self._parse_spot(workbook, sheet))
            elif "FORWARD" in name_upper:
                fwd_rows.extend(self._parse_forward(workbook, sheet))
            else:
                ts_rows.extend(self._parse_timeseries(workbook, sheet))

        return ParsedCurvesWorkbook(
            source_path=source_path,
            timeseries=pd.DataFrame(ts_rows) if ts_rows else pd.DataFrame(),
            spot=pd.DataFrame(spot_rows) if spot_rows else pd.DataFrame(),
            forward=pd.DataFrame(fwd_rows) if fwd_rows else pd.DataFrame()
        )

    def _parse_spot(self, workbook: pd.ExcelFile, sheet: str) -> list[dict[str, Any]]:
        df = pd.read_excel(workbook, sheet_name=sheet, header=None, skiprows=1, engine="openpyxl")
        out = []
        current_group = ""
        for _, row in df.iterrows():
            val = str(row.iloc[0]).strip()
            if val == "nan" or val == "":
                continue
            if ":" not in val:
                current_group = val
            else:
                parts = val.split(":", 1)
                if len(parts) == 2:
                    out.append({
                        "Groep": current_group,
                        "Parameter": parts[0].strip(),
                        "Waarde": self._safe_float(parts[1]),
                        "SourceSheet": sheet,
                    })
        return out

    def _parse_forward(self, workbook: pd.ExcelFile, sheet: str) -> list[dict[str, Any]]:
        df = pd.read_excel(workbook, sheet_name=sheet, header=2, engine="openpyxl")
        out = []
        if df.empty or len(df.columns) < 5:
            return out
        for _, row in df.iterrows():
            if pd.isna(row.iloc[0]):
                continue
            out.append({
                "Datum": self._format_ts(row.iloc[0]),
                "Energietype": str(row.iloc[1]).strip(),
                "Indexatieparameter": str(row.iloc[2]).strip(),
                "Afname_VNR": self._safe_float(row.iloc[3]),
                "Teruglevering_VNR": self._safe_float(row.iloc[4]),
                "SourceSheet": sheet,
            })
        return out

    def _parse_timeseries(self, workbook: pd.ExcelFile, sheet: str) -> list[dict[str, Any]]:
        df = pd.read_excel(workbook, sheet_name=sheet, engine="openpyxl")
        if df.empty:
            return []

        name_lower = sheet.lower()
        curve_type = "UNKNOWN"
        if "epc" in name_lower: curve_type = "EPC"
        elif "rlp" in name_lower: curve_type = "RLP"
        elif "spp" in name_lower: curve_type = "SPP"

        energy_type = "UNKNOWN"
        if "elek" in name_lower: energy_type = "Elektriciteit"
        elif "gas" in name_lower: energy_type = "Gas"
        elif "tlc" in name_lower: energy_type = "Elektriciteit_Injectie"

        resolution = "UNKNOWN"
        if "kwartier" in name_lower: resolution = "15Min"
        elif "uur" in name_lower: resolution = "1H"
        else:
            if curve_type == "EPC" and energy_type == "Elektriciteit": resolution = "1H"
            else: resolution = "1D"

        time_col = df.columns[0]
        # Melt = draait alle kolommen naast de Timestamp om naar rijen! Heel handig voor simulaties.
        df_melt = df.melt(id_vars=[time_col], var_name="Variant", value_name="Waarde")

        out = []
        for _, row in df_melt.iterrows():
            if pd.isna(row["Waarde"]):
                continue
            out.append({
                "Timestamp": self._format_ts(row[time_col]),
                "CurveType": curve_type,
                "EnergyType": energy_type,
                "Resolution": resolution,
                "Variant": str(row["Variant"]).strip(),
                "Waarde": self._safe_float(row["Waarde"]),
                "SourceSheet": sheet,
            })
        return out

    @staticmethod
    def _format_ts(val: Any) -> str:
        if isinstance(val, pd.Timestamp):
            return val.isoformat()
        return str(val).strip()

    @staticmethod
    def _safe_float(val: Any) -> float | None:
        if pd.isna(val) or str(val).strip() == "":
            return None
        try:
            val_str = str(val).replace(",", ".")
            return float(val_str)
        except ValueError:
            return None