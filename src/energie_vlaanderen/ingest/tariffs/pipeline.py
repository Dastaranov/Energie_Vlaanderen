from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json

from energie_vlaanderen.ingest.tariffs.normalizer import NormalizedTariffData, TariffDataNormalizer
from energie_vlaanderen.ingest.tariffs.validator import TariffDataValidator, TariffValidationReport
from energie_vlaanderen.ingest.tariffs.workbook import ParsedTariffWorkbook, TariffWorkbookParser


class TariffPipelineError(RuntimeError):
    pass


@dataclass(frozen=True)
class TariffPipelineResult:
    version_id: str
    directory: Path
    afname_csv: Path
    injectie_csv: Path
    report_json: Path


class TariffPipeline:
    def __init__(self) -> None:
        self.workbook_parser = TariffWorkbookParser()
        self.normalizer = TariffDataNormalizer()
        self.validator = TariffDataValidator()

    def process(
        self,
        source_path: Path,
        destination: Path,
        version_id: str,
        overwrite: bool = False,
    ) -> TariffPipelineResult:
        parsed = self.workbook_parser.parse(source_path)
        normalized = self.normalizer.normalize(parsed.afname, parsed.injectie)
        validation = self.validator.validate(normalized.afname, normalized.injectie)

        if normalized.errors or not validation.valid:
            raise TariffPipelineError("Tariefdata bevat blokkerende fouten en werd niet geëxporteerd.")

        target = destination / "tariffs"
        if target.exists():
            if not overwrite:
                raise TariffPipelineError(
                    f"Tarieven stagingmap bestaat al: {target}. "
                    "Gebruik --overwrite om deze te overschrijven."
                )
            shutil.rmtree(target)

        target.mkdir(parents=True, exist_ok=False)
        afname_csv = target / "tariffs_afname.csv"
        injectie_csv = target / "tariffs_injectie.csv"
        report_json = target / "tariffs_report.json"

        try:
            self._write_frame(normalized.afname, afname_csv)
            self._write_frame(normalized.injectie, injectie_csv)

            report = {
                "version_id": version_id,
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "afname_rows": len(normalized.afname),
                "injectie_rows": len(normalized.injectie),
            }
            report_json.write_text(json.dumps(report, indent=2), encoding="utf-8")

        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise

        return TariffPipelineResult(
            version_id=version_id,
            directory=target,
            afname_csv=afname_csv,
            injectie_csv=injectie_csv,
            report_json=report_json,
        )

    @staticmethod
    def _write_frame(frame: pd.DataFrame, path: Path) -> None:
        frame.to_csv(path, sep=";", index=False, encoding="utf-8-sig")