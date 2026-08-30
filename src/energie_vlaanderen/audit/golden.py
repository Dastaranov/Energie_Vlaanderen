from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd

from energie_vlaanderen.ingest.vtest.workbook import VTestWorkbookParser
from energie_vlaanderen.ingest.vtest.normalizer import VTestDataNormalizer
from energie_vlaanderen.ingest.tariffs.workbook import TariffWorkbookParser
from energie_vlaanderen.ingest.tariffs.normalizer import TariffDataNormalizer


@dataclass(frozen=True)
class FieldMismatch:
    domain: str
    source_sheet: str
    source_row: int | None
    field: str
    csv_value: str
    xlsx_value: str
    row_key: str


@dataclass(frozen=True)
class GoldenAuditResult:
    version_id: str
    domain: str
    source_xlsx: Path
    total_rows: int
    verified_rows: int
    mismatches: tuple[FieldMismatch, ...]

    @property
    def passed(self) -> bool:
        return not self.mismatches


class VTestGoldenAuditor:
    COMPARE_FIELDS = (
        "year", "month", "segment", "energy", "direction",
        "supplier", "product", "product_type", "component",
        "component_label", "price", "a", "b", "c", "d", "z",
        "index_name_A", "index_name_B", "index_name_C", "index_name_D",
        "index_value_A", "index_value_B", "index_value_C", "index_value_D",
    )

    DECIMAL_FIELDS = frozenset({
        "price", "a", "b", "c", "d", "z",
        "index_value_A", "index_value_B", "index_value_C", "index_value_D",
    })

    def audit(
        self,
        staged_csv: Path,
        source_xlsx: Path,
        domain: str,
        version_id: str,
    ) -> GoldenAuditResult:
        parsed = VTestWorkbookParser().parse(source_xlsx)
        if domain.endswith("_vast"):
            fresh_df = VTestDataNormalizer().normalize(parsed.fixed, pd.DataFrame()).fixed
        else:
            fresh_df = VTestDataNormalizer().normalize(pd.DataFrame(), parsed.variable_dynamic).variable_dynamic

        if not staged_csv.is_file():
            return GoldenAuditResult(
                version_id=version_id,
                domain=domain,
                source_xlsx=source_xlsx,
                total_rows=0,
                verified_rows=0,
                mismatches=(),
            )

        staged_df = pd.read_csv(staged_csv, sep=";", dtype=str, encoding="utf-8-sig").fillna("")

        # Build lookup: (source_sheet, source_row) → dict of fresh values
        fresh_index: dict[tuple[str, int], dict[str, Any]] = {}
        for _, row in fresh_df.iterrows():
            ss = str(row.get("source_sheet", ""))
            sr_raw = row.get("source_row")
            try:
                sr = int(sr_raw)
            except (ValueError, TypeError):
                continue
            fresh_index[(ss, sr)] = dict(row)

        mismatches: list[FieldMismatch] = []
        verified = 0

        for _, csv_row in staged_df.iterrows():
            ss = str(csv_row.get("source_sheet", "")).strip()
            sr_raw = csv_row.get("source_row", "")
            try:
                sr = int(float(sr_raw))
            except (ValueError, TypeError):
                continue

            fresh_row = fresh_index.get((ss, sr))
            if fresh_row is None:
                continue

            row_key = (
                f"{csv_row.get('supplier', '')} / {csv_row.get('product', '')} / "
                f"{csv_row.get('year', '')}-{csv_row.get('month', '')} / "
                f"{csv_row.get('component', '')}"
            )
            verified += 1

            for field in self.COMPARE_FIELDS:
                csv_val = str(csv_row.get(field, "")).strip()
                fresh_val = fresh_row.get(field)

                if field in self.DECIMAL_FIELDS:
                    if not _decimals_equal(csv_val, fresh_val):
                        mismatches.append(FieldMismatch(
                            domain=domain,
                            source_sheet=ss,
                            source_row=sr,
                            field=field,
                            csv_value=csv_val,
                            xlsx_value=str(fresh_val),
                            row_key=row_key,
                        ))
                else:
                    fresh_str = str(fresh_val).strip() if fresh_val is not None else ""
                    if csv_val != fresh_str:
                        mismatches.append(FieldMismatch(
                            domain=domain,
                            source_sheet=ss,
                            source_row=sr,
                            field=field,
                            csv_value=csv_val,
                            xlsx_value=fresh_str,
                            row_key=row_key,
                        ))

        return GoldenAuditResult(
            version_id=version_id,
            domain=domain,
            source_xlsx=source_xlsx,
            total_rows=len(staged_df),
            verified_rows=verified,
            mismatches=tuple(mismatches),
        )


class TariffGoldenAuditor:
    COMPARE_FIELDS = (
        "Netbeheerder", "Contracttype", "Klanttype",
        "Tarieftype", "Tariefdetail", "Tariefnotering", "Prijs_num",
    )
    FLOAT_TOLERANCE = 1e-4
    SORT_KEYS = ["Netbeheerder", "Contracttype", "Klanttype", "Tarieftype", "Tariefdetail", "source_sheet", "source_row"]

    def audit(
        self,
        staged_csv: Path,
        source_xlsx: Path,
        energy_type: str,
        direction: str,
        version_id: str,
    ) -> GoldenAuditResult:
        domain = f"{energy_type}_{direction}"
        parsed = TariffWorkbookParser().parse(source_xlsx, energy_type=energy_type)
        if direction == "afname":
            fresh_df = TariffDataNormalizer().normalize(parsed.afname, pd.DataFrame()).afname
        else:
            fresh_df = TariffDataNormalizer().normalize(pd.DataFrame(), parsed.injectie).injectie

        if not staged_csv.is_file():
            return GoldenAuditResult(
                version_id=version_id,
                domain=domain,
                source_xlsx=source_xlsx,
                total_rows=0,
                verified_rows=0,
                mismatches=(),
            )

        staged_df = pd.read_csv(staged_csv, sep=";", dtype=str, encoding="utf-8-sig").fillna("")

        sort_keys_fresh = [k for k in self.SORT_KEYS if k in fresh_df.columns]
        sort_keys_staged = [k for k in self.SORT_KEYS if k in staged_df.columns]
        fresh_sorted = fresh_df.sort_values(sort_keys_fresh).reset_index(drop=True) if sort_keys_fresh else fresh_df.reset_index(drop=True)
        staged_sorted = staged_df.sort_values(sort_keys_staged).reset_index(drop=True) if sort_keys_staged else staged_df.reset_index(drop=True)

        mismatches: list[FieldMismatch] = []
        total = len(staged_sorted)
        verified = min(len(fresh_sorted), len(staged_sorted))

        if len(fresh_sorted) != len(staged_sorted):
            mismatches.append(FieldMismatch(
                domain=domain,
                source_sheet="",
                source_row=None,
                field="_row_count",
                csv_value=str(len(staged_sorted)),
                xlsx_value=str(len(fresh_sorted)),
                row_key="totaal",
            ))

        for idx in range(verified):
            fresh_row = fresh_sorted.iloc[idx]
            staged_row = staged_sorted.iloc[idx]

            ss = str(staged_row.get("source_sheet", "")).strip()
            sr_raw = staged_row.get("source_row", "")
            try:
                sr: int | None = int(float(sr_raw))
            except (ValueError, TypeError):
                sr = None

            row_key = (
                f"{staged_row.get('Netbeheerder', '')} / "
                f"{staged_row.get('Tariefdetail', '')} / "
                f"{staged_row.get('Klanttype', '')}"
            )

            for field in self.COMPARE_FIELDS:
                csv_val = str(staged_row.get(field, "")).strip()
                fresh_val = fresh_row.get(field)
                fresh_str = str(fresh_val) if fresh_val is not None else ""

                if field == "Prijs_num":
                    if not _floats_equal(csv_val, fresh_str, self.FLOAT_TOLERANCE):
                        mismatches.append(FieldMismatch(
                            domain=domain,
                            source_sheet=ss,
                            source_row=sr,
                            field=field,
                            csv_value=csv_val,
                            xlsx_value=fresh_str,
                            row_key=row_key,
                        ))
                else:
                    if csv_val != fresh_str.strip():
                        mismatches.append(FieldMismatch(
                            domain=domain,
                            source_sheet=ss,
                            source_row=sr,
                            field=field,
                            csv_value=csv_val,
                            xlsx_value=fresh_str,
                            row_key=row_key,
                        ))

        return GoldenAuditResult(
            version_id=version_id,
            domain=domain,
            source_xlsx=source_xlsx,
            total_rows=total,
            verified_rows=verified,
            mismatches=tuple(mismatches),
        )


def _decimals_equal(csv_val: str, fresh_val: Any) -> bool:
    """Compare a CSV decimal string (Belgian comma) with a fresh Decimal/None value."""
    # Parse fresh value
    if fresh_val is None or str(fresh_val) in ("None", "nan", ""):
        fresh_dec: Decimal | None = None
    else:
        try:
            fresh_dec = Decimal(str(fresh_val))
        except InvalidOperation:
            fresh_dec = None

    # Parse CSV value — Belgian comma format
    if csv_val in ("", "None", "nan"):
        csv_dec: Decimal | None = None
    else:
        try:
            csv_dec = Decimal(csv_val.replace(",", "."))
        except InvalidOperation:
            csv_dec = None

    if csv_dec is None and fresh_dec is None:
        return True
    if csv_dec is None:
        return fresh_dec == Decimal("0")
    if fresh_dec is None:
        return csv_dec == Decimal("0")
    return csv_dec == fresh_dec


def _floats_equal(csv_val: str, fresh_val: str, tolerance: float) -> bool:
    """Compare two float strings within a tolerance."""
    try:
        a = float(csv_val)
        b = float(fresh_val)
        return abs(a - b) <= tolerance
    except (ValueError, TypeError):
        return csv_val == fresh_val
