from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from energie_vlaanderen.ingest.vtest.normalizer import NormalizedVTestData, VTestDataNormalizer
from energie_vlaanderen.ingest.vtest.validator import VTestDataValidator, VTestValidationReport
from energie_vlaanderen.ingest.vtest.workbook import (
    ParsedVTestWorkbook,
    VTestWorkbookError,
    VTestWorkbookParser,
)


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
        # Stap 1 Parser starten
        try:
            parsed = self.workbook_parser.parse(source_path)
        except VTestWorkbookError as exc:
            raise VTestPipelineError(str(exc)) from exc

        # Stap 2 Normalizer starten
        normalized = self.normalizer.normalize(
            parsed.fixed,
            parsed.variable_dynamic,
        )

        if normalized.errors:
            examples = "\n".join(
                (
                    f"- {issue.source_sheet}:"
                    f"{issue.source_row}: "
                    f"{issue.message}"
                )
                for issue in normalized.errors[:20]
            )
            raise VTestPipelineError(
                "Normalisatie bevat "
                f"{len(normalized.errors)} fouten. "
                f"Eerste 20 voorbeelden:\n{examples}"
            )
        
        validation = self.validator.validate(
            parsed=parsed,
            fixed=normalized.fixed,
            variable_dynamic=normalized.variable_dynamic,
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
        fixed_csv = target / "master_vast.csv"
        variable_csv = target / "master_var_dyn.csv"
        report_json = target / "pipeline_report.json"

        # De map zelf mag al bestaan: `staging refine` schrijft zijn
        # scrape-resultaten in dezelfde vtest-map, en die mogen niet verloren
        # gaan bij een herparse. Wat níet overschreven mag worden zonder dat
        # de caller er expliciet om vroeg, zijn de parse-outputs zelf — de
        # caller ruimt die op voor hij ons aanroept.
        bestaand = [pad for pad in (fixed_csv, variable_csv, report_json) if pad.exists()]
        if bestaand:
            namen = ", ".join(pad.name for pad in bestaand)
            raise VTestPipelineError(
                f"V-test parse-output bestaat al in {target}: {namen}."
            )

        target.mkdir(parents=True, exist_ok=True)

        # Naar tijdelijke bestanden, en pas omwisselen als alles gelukt is.
        # Hier stond `shutil.rmtree(target)` in de foutafhandeling -- op precies
        # de map waarvan het commentaar hierboven zegt dat de refine-output er
        # niet uit mag verdwijnen. Eén schrijffout wiste dan een Selenium-scrape
        # van een half uur plus alle opgehaalde contractdetails.
        tijdelijk = [pad.with_suffix(pad.suffix + ".tijdelijk")
                     for pad in (fixed_csv, variable_csv, report_json)]
        tmp_fixed, tmp_variable, tmp_report = tijdelijk

        try:
            self._write_frame(normalized.fixed, tmp_fixed)
            self._write_frame(normalized.variable_dynamic, tmp_variable)

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

            tmp_report.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            # Alles is geschreven; nu pas de drie artefacten op hun plaats.
            os.replace(tmp_fixed, fixed_csv)
            os.replace(tmp_variable, variable_csv)
            os.replace(tmp_report, report_json)
        except Exception:
            # Alleen ons eigen gerommel opruimen. De map blijft staan, met
            # alles wat er van andere stappen in zit.
            for pad in tijdelijk:
                pad.unlink(missing_ok=True)
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