from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from .vtest_normalizer import NormalizedVTestData, VTestDataNormalizer
from .vtest_validator import VTestDataValidator, VTestValidationReport
from .vtest_workbook import ParsedVTestWorkbook, VTestWorkbookParser


class VTestPipelineError(RuntimeError):
    pass


@dataclass(frozen=True)
class VTestPipelineResult:
    version_id: str
    source_path: Path
    directory: Path
    fixed_csv: Path
    variable_dynamic_csv: Path
    report_json: Path
    fixed_rows: int
    variable_dynamic_rows: int
    normalization_warnings: int
    validation_warnings: int


class VTestPipeline:
    def __init__(
        self,
        workbook_parser: VTestWorkbookParser | None = None,
        normalizer: VTestDataNormalizer | None = None,
        validator: VTestDataValidator | None = None,
    ) -> None:
        self.workbook_parser = workbook_parser or VTestWorkbookParser()
        self.normalizer = normalizer or VTestDataNormalizer()
        self.validator = validator or VTestDataValidator()

    def process(
        self,
        source_path: Path,
        destination: Path,
        version_id: str,
    ) -> VTestPipelineResult:
        parsed = self.workbook_parser.parse(source_path)
        normalized = self.normalizer.normalize(
            parsed.fixed,
            parsed.variable_dynamic,
        )
        validation = self.validator.validate(
            normalized.fixed,
            normalized.variable_dynamic,
        )

        normalization_errors = normalized.errors
        if normalization_errors or not validation.valid:
            messages = [
                self._normalization_issue_text(issue)
                for issue in normalization_errors
            ]
            messages.extend(
                self._validation_issue_text(issue)
                for issue in validation.errors
            )
            formatted = "\n".join(f"  - {message}" for message in messages)
            raise VTestPipelineError(
                "V-testdata bevat blokkerende fouten en werd niet geëxporteerd:\n"
                + formatted
            )

        return self._write_output(
            parsed=parsed,
            normalized=normalized,
            validation=validation,
            destination=destination,
            version_id=version_id,
        )

    def _write_output(
        self,
        parsed: ParsedVTestWorkbook,
        normalized: NormalizedVTestData,
        validation: VTestValidationReport,
        destination: Path,
        version_id: str,
    ) -> VTestPipelineResult:
        target = destination / "vtest"
        if target.exists():
            raise VTestPipelineError(f"V-test stagingmap bestaat al: {target}")

        target.mkdir(parents=True, exist_ok=False)
        fixed_csv = target / "master_vast.csv"
        variable_csv = target / "master_var_dyn.csv"
        report_json = target / "pipeline_report.json"

        try:
            self._write_frame(normalized.fixed, fixed_csv)
            self._write_frame(normalized.variable_dynamic, variable_csv)

            report = {
                "schema_version": 1,
                "version_id": version_id,
                "source_path": str(parsed.source_path),
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "fixed_rows": len(normalized.fixed),
                "variable_dynamic_rows": len(normalized.variable_dynamic),
                "workbook_warnings": list(parsed.warnings),
                "normalization_issues": [
                    {
                        "severity": issue.severity,
                        "message": issue.message,
                        "source_sheet": issue.source_sheet,
                        "source_row": issue.source_row,
                    }
                    for issue in normalized.issues
                ],
                "validation_issues": [
                    {
                        "severity": issue.severity,
                        "code": issue.code,
                        "message": issue.message,
                        "source_sheet": issue.source_sheet,
                        "source_row": issue.source_row,
                    }
                    for issue in validation.issues
                ],
                "sheets": [
                    {
                        "sheet_name": sheet.sheet_name,
                        "header_row": sheet.header_row,
                        "rows": sheet.rows,
                        "columns": list(sheet.columns),
                    }
                    for sheet in parsed.sheets
                ],
            }

            temporary = report_json.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, report_json)
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise

        return VTestPipelineResult(
            version_id=version_id,
            source_path=parsed.source_path,
            directory=target,
            fixed_csv=fixed_csv,
            variable_dynamic_csv=variable_csv,
            report_json=report_json,
            fixed_rows=len(normalized.fixed),
            variable_dynamic_rows=len(normalized.variable_dynamic),
            normalization_warnings=len(normalized.warnings),
            validation_warnings=len(validation.warnings),
        )

    @staticmethod
    def _write_frame(frame: pd.DataFrame, path: Path) -> None:
        export = frame.copy()
        for column in export.columns:
            export[column] = export[column].map(VTestPipeline._csv_value)
        export.to_csv(
            path,
            sep=";",
            index=False,
            encoding="utf-8-sig",
        )

    @staticmethod
    def _csv_value(value: Any) -> Any:
        if value is None:
            return ""
        try:
            if bool(pd.isna(value)):
                return ""
        except (TypeError, ValueError):
            pass
        if isinstance(value, Decimal):
            return format(value, "f").replace(".", ",")
        return value

    @staticmethod
    def _normalization_issue_text(issue: Any) -> str:
        location = VTestPipeline._location(issue.source_sheet, issue.source_row)
        return f"normalisatie {location}: {issue.message}"

    @staticmethod
    def _validation_issue_text(issue: Any) -> str:
        location = VTestPipeline._location(issue.source_sheet, issue.source_row)
        return f"validatie [{issue.code}] {location}: {issue.message}"

    @staticmethod
    def _location(sheet: str, row: int | None) -> str:
        sheet_text = sheet or "onbekend werkblad"
        row_text = "?" if row is None else str(row)
        return f"{sheet_text}, rij {row_text}"