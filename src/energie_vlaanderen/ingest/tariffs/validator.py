from __future__ import annotations
from dataclasses import dataclass
import pandas as pd

@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    message: str
    source_sheet: str

@dataclass(frozen=True)
class TariffValidationReport:
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

class TariffDataValidator:
    KEY_COLUMNS = ("dnb", "direction", "omschrijving")

    def validate(self, afname: pd.DataFrame, injectie: pd.DataFrame) -> TariffValidationReport:
        issues: list[ValidationIssue] = []
        self._validate_frame(afname, issues)
        self._validate_frame(injectie, issues)
        return TariffValidationReport(issues=tuple(issues))

    def _validate_frame(self, frame: pd.DataFrame, issues: list[ValidationIssue]) -> None:
        if frame.empty:
            return

        missing_columns = [col for col in self.KEY_COLUMNS if col not in frame.columns]
        if missing_columns:
            issues.append(ValidationIssue(
                severity="error", 
                code="missing_columns",
                message=f"Verplichte kolommen ontbreken: {', '.join(missing_columns)}",
                source_sheet=""
            ))
            return

        for _, row in frame.iterrows():
            if not row.get("dnb") or row.get("dnb") == "Onbekende DNB":
                issues.append(ValidationIssue(
                    severity="error",
                    code="unknown_dnb",
                    message="Netbeheerder kon niet bepaald worden uit het tabblad.",
                    source_sheet=str(row.get("source_sheet", ""))
                ))