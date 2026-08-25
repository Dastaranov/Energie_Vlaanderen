from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    message: str
    source_sheet: str
    source_row: int | None


@dataclass(frozen=True)
class VTestValidationReport:
    issues: tuple[ValidationIssue, ...]

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def valid(self) -> bool:
        return not self.errors


class VTestDataValidator:
    KEY_COLUMNS = (
        "year",
        "month",
        "segment",
        "energy",
        "direction",
        "supplier",
        "product",
        "product_type",
        "component",
    )

    def validate(
        self,
        fixed: pd.DataFrame,
        variable_dynamic: pd.DataFrame,
    ) -> VTestValidationReport:
        issues: list[ValidationIssue] = []

        self._validate_frame(
            fixed,
            expected_types={"vast"},
            issues=issues,
        )
        self._validate_frame(
            variable_dynamic,
            expected_types={"variabel", "dynamisch"},
            issues=issues,
        )

        return VTestValidationReport(issues=tuple(issues))

    def _validate_frame(
        self,
        frame: pd.DataFrame,
        expected_types: set[str],
        issues: list[ValidationIssue],
    ) -> None:
        if frame.empty:
            return

        missing_columns = [
            column for column in self.KEY_COLUMNS if column not in frame.columns
        ]
        if missing_columns:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="missing_columns",
                    message=(
                        "Verplichte genormaliseerde kolommen ontbreken: "
                        + ", ".join(missing_columns)
                    ),
                    source_sheet="",
                    source_row=None,
                )
            )
            return

        duplicate_mask = frame.duplicated(
            subset=list(self.KEY_COLUMNS),
            keep=False,
        )
        for _, row in frame.loc[duplicate_mask].iterrows():
            self._add_issue(
                issues,
                row,
                severity="error",
                code="duplicate_component",
                message=(
                    "Dubbele productcomponent voor "
                    f"{row.get('supplier')} / {row.get('product')} / "
                    f"{row.get('component')}."
                ),
            )

        for _, row in frame.iterrows():
            product_type = str(row.get("product_type", "")).casefold()

            if product_type not in expected_types:
                self._add_issue(
                    issues,
                    row,
                    severity="error",
                    code="unexpected_product_type",
                    message="Producttype staat in de verkeerde genormaliseerde tabel.",
                )
                continue

            has_price = not self._is_missing(row.get("price"))
            has_formula = self._has_formula(row)

            if product_type == "vast" and not has_price:
                self._add_issue(
                    issues,
                    row,
                    severity="error",
                    code="fixed_price_missing",
                    message="Vast prijsonderdeel heeft geen prijs.",
                )

            if product_type == "variabel" and not has_price and not has_formula:
                self._add_issue(
                    issues,
                    row,
                    severity="error",
                    code="variable_price_missing",
                    message=(
                        "Variabel prijsonderdeel heeft geen prijs en geen "
                        "bruikbare indexatieformule."
                    ),
                )

            if product_type == "dynamisch" and not has_price and not has_formula:
                self._add_issue(
                    issues,
                    row,
                    severity="error",
                    code="dynamic_formula_missing",
                    message=(
                        "Dynamisch prijsonderdeel heeft geen prijs en geen "
                        "bruikbare formule."
                    ),
                )

            for coefficient, index_letter in (
                ("a", "A"),
                ("b", "B"),
                ("c", "C"),
                ("d", "D"),
            ):
                coefficient_value = self._decimal(row.get(coefficient))
                index_value = row.get(f"index_value_{index_letter}")

                if (
                    coefficient_value != Decimal("0")
                    and self._is_missing(index_value)
                ):
                    self._add_issue(
                        issues,
                        row,
                        severity="warning",
                        code="index_value_missing",
                        message=(
                            f"Coefficient {coefficient} is niet nul, maar "
                            f"indexwaarde {index_letter} ontbreekt."
                        ),
                    )

    @classmethod
    def _has_formula(cls, row: pd.Series) -> bool:
        return any(
            cls._decimal(row.get(column)) != Decimal("0")
            for column in ("a", "b", "c", "d", "z")
        )

    @classmethod
    def _decimal(cls, value: Any) -> Decimal:
        if cls._is_missing(value):
            return Decimal("0")
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value).replace(",", "."))
        except (InvalidOperation, ValueError, TypeError):
            return Decimal("0")

    @staticmethod
    def _is_missing(value: Any) -> bool:
        if value is None:
            return True
        try:
            missing = pd.isna(value)
            return bool(missing) if not isinstance(missing, (list, tuple)) else False
        except (TypeError, ValueError):
            return False

    @classmethod
    def _source_row(cls, value: Any) -> int | None:
        if cls._is_missing(value):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _add_issue(
        cls,
        issues: list[ValidationIssue],
        row: pd.Series,
        severity: str,
        code: str,
        message: str,
    ) -> None:
        source_sheet_value = row.get("source_sheet", "")
        source_sheet = "" if cls._is_missing(source_sheet_value) else str(source_sheet_value)
        issues.append(
            ValidationIssue(
                severity=severity,
                code=code,
                message=message,
                source_sheet=source_sheet,
                source_row=cls._source_row(row.get("source_row")),
            )
        )