from __future__ import annotations
from dataclasses import dataclass
import pandas as pd

@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    message: str

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
    # Dit zijn de verplichte kolommen die calculator.py nodig heeft
    KEY_COLUMNS = ("Netbeheerder", "Contracttype", "Klanttype", "Tarieftype", "Tariefdetail", "Tariefnotering", "Prijs_num")

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
                message=f"Verplichte kolommen ontbreken: {', '.join(missing_columns)}"
            ))
            return