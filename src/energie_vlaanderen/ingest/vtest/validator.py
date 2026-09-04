from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from collections import Counter

import pandas as pd

from energie_vlaanderen.ingest.vtest.normalizer import NormalizedVTestData
from energie_vlaanderen.ingest.vtest.workbook import ParsedVTestWorkbook

SourceReference = tuple[str, int]


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
        parsed: ParsedVTestWorkbook,
        fixed: pd.DataFrame,
        variable_dynamic: pd.DataFrame,
    ) -> VTestValidationReport:
        issues: list[ValidationIssue] = []
        issues.extend(
            self._validate_source_coverage(
                parsed=parsed,
                fixed=fixed,
                variable_dynamic=variable_dynamic,
            )
        )

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
                severity="warning",
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

    def validate_source_coverage(
        self,
        parsed: ParsedVTestWorkbook,
        normalized: NormalizedVTestData,
    ) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []

        output = pd.concat(
            [
                normalized.fixed,
                normalized.variable_dynamic,
            ],
            ignore_index=True,
            sort=False,
        )

        if output.empty:
            return (
                ValidationIssue(
                    severity="error",
                    code="NO_OUTPUT_ROWS",
                    message="Geen genormaliseerde rijen gevonden.",
                    source_sheet="",
                    source_row=None,
                ),
            )

        source_keys = output[
            ["source_sheet", "source_row"]
        ].copy()

        duplicate_mask = source_keys.duplicated(
            keep=False
        )

        for _, row in source_keys.loc[
            duplicate_mask
        ].iterrows():
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="DUPLICATE_SOURCE_ROW",
                    message=(
                        "Bronrij komt meerdere keren voor "
                        "in de uitvoer."
                    ),
                    source_sheet=str(
                        row["source_sheet"]
                    ),
                    source_row=int(
                        row["source_row"]
                    ),
                )
            )

        for sheet in parsed.sheets:
            expected = set(sheet.source_rows)

            actual = set(
                output.loc[
                    output["source_sheet"].eq(
                        sheet.sheet_name
                    ),
                    "source_row",
                ]
                .dropna()
                .astype(int)
            )

            missing = sorted(expected - actual)
            unexpected = sorted(actual - expected)

            for source_row in missing:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="MISSING_SOURCE_ROW",
                        message=(
                            "Bronrij ontbreekt in de uitvoer."
                        ),
                        source_sheet=sheet.sheet_name,
                        source_row=source_row,
                    )
                )

            for source_row in unexpected:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="UNEXPECTED_SOURCE_ROW",
                        message=(
                            "Uitvoerrij heeft geen "
                            "overeenkomstige bronrij."
                        ),
                        source_sheet=sheet.sheet_name,
                        source_row=source_row,
                    )
                )

            actual_rows = len(actual)
            if actual_rows != sheet.rows:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="SOURCE_ROW_COUNT_MISMATCH",
                        message=(
                            f"Werkblad bevat {sheet.rows} "
                            "bronrijen, maar de uitvoer bevat "
                            f"{actual_rows} rijen."
                        ),
                        source_sheet=sheet.sheet_name,
                        source_row=None,
                    )
                )

        return tuple(issues)

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

    @staticmethod
    def _expected_source_references(
        parsed: ParsedVTestWorkbook,
    ) -> set[SourceReference]:
        """
        Geef alle door de parser gevonden bronrijen terug.

        Iedere combinatie van werkblad en Excel-rijnummer
        moet exact eenmaal in de genormaliseerde uitvoer voorkomen.
        """
        references: set[SourceReference] = set()

        for sheet in parsed.sheets:
            for source_row in sheet.source_rows:
                reference = (
                    sheet.sheet_name,
                    int(source_row),
                )

                if reference in references:
                    raise ValueError(
                        "Dubbele bronreferentie in parserresultaat: "
                        f"{sheet.sheet_name}, rij {source_row}."
                    )

                references.add(reference)
        return references

    @staticmethod
    def _actual_source_references(
        frame: pd.DataFrame,
    ) -> list[SourceReference]:
        """
        Lees de bronreferenties uit een genormaliseerd DataFrame.

        Een list wordt gebruikt zodat dubbele referenties
        nog gedetecteerd kunnen worden.
        """
        if frame.empty:
            return []

        required_columns = {
            "source_sheet",
            "source_row",
        }

        missing_columns = required_columns - set(frame.columns)

        if missing_columns:
            raise ValueError(
                "Genormaliseerde dataset mist bronkolommen: "
                + ", ".join(sorted(missing_columns))
            )

        references: list[SourceReference] = []

        for row in frame[
            ["source_sheet", "source_row"]
        ].itertuples(index=False):
            source_sheet = str(row.source_sheet).strip()

            if not source_sheet:
                raise ValueError(
                    "Lege source_sheet in genormaliseerde dataset."
                )

            if pd.isna(row.source_row):
                raise ValueError(
                    "Lege source_row in genormaliseerde dataset."
                )

            references.append(
                (
                    source_sheet,
                    int(row.source_row),
                )
            )

        return references

    @classmethod
    def _validate_source_coverage(
        cls,
        parsed: ParsedVTestWorkbook,
        fixed: pd.DataFrame,
        variable_dynamic: pd.DataFrame,
    ) -> list[ValidationIssue]:
        """
        Controleer dat iedere geparste bronrij exact eenmaal
        in precies één uitvoertabel voorkomt.
        """
        issues: list[ValidationIssue] = []

        expected = cls._expected_source_references(parsed)

        fixed_references = cls._actual_source_references(fixed)
        variable_references = cls._actual_source_references(
            variable_dynamic
        )

        all_actual = fixed_references + variable_references
        actual_set = set(all_actual)

        missing = sorted(expected - actual_set)
        unexpected = sorted(actual_set - expected)

        fixed_set = set(fixed_references)
        variable_set = set(variable_references)

        wrong_table_overlap = sorted(
            fixed_set & variable_set
        )

        reference_counts = Counter(all_actual)

        duplicate_references = sorted(
            reference
            for reference, count in reference_counts.items()
            if count > 1
        )

        for source_sheet, source_row in missing:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="missing_source_row",
                    message=(
                        "Geparste bronrij ontbreekt in de "
                        "genormaliseerde uitvoer."
                    ),
                    source_sheet=source_sheet,
                    source_row=source_row,
                )
            )

        for source_sheet, source_row in unexpected:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="unexpected_source_row",
                    message=(
                        "Uitvoerrij verwijst naar een bronrij "
                        "die niet in het parserresultaat voorkomt."
                    ),
                    source_sheet=source_sheet,
                    source_row=source_row,
                )
            )

        for source_sheet, source_row in duplicate_references:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="duplicate_source_row",
                    message=(
                        "Bronrij komt meer dan eenmaal voor "
                        "in de genormaliseerde uitvoer."
                    ),
                    source_sheet=source_sheet,
                    source_row=source_row,
                )
            )

        for source_sheet, source_row in wrong_table_overlap:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="source_row_in_both_tables",
                    message=(
                        "Bronrij komt zowel in de vaste als in "
                        "de variabele/dynamische uitvoer voor."
                    ),
                    source_sheet=source_sheet,
                    source_row=source_row,
                )
            )

        return issues