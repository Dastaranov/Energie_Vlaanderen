from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from energie_vlaanderen.ingest.curves.workbook import CurvesWorkbookParser


class CurvesPipelineError(RuntimeError):
    pass


@dataclass(frozen=True)
class CurvesPipelineResult:
    version_id: str
    directory: Path
    timeseries_csv: Path
    spot_csv: Path
    forward_csv: Path
    report_json: Path


class CurvesPipeline:
    def __init__(self) -> None:
        self.workbook_parser = CurvesWorkbookParser()

    def process(
        self,
        source_path: Path,
        destination: Path,
        version_id: str,
        overwrite: bool = False,
    ) -> CurvesPipelineResult:
        parsed = self.workbook_parser.parse(source_path)

        target = destination / "curves"
        if target.exists():
            if not overwrite:
                raise CurvesPipelineError(
                    f"Curves stagingmap bestaat al: {target}. "
                    "Gebruik --overwrite om deze te overschrijven."
                )
            shutil.rmtree(target)

        target.mkdir(parents=True, exist_ok=False)
        timeseries_csv = target / "curves_timeseries.csv"
        spot_csv = target / "curves_spot.csv"
        forward_csv = target / "curves_forward.csv"
        report_json = target / "curves_report.json"

        try:
            self._write_frame(parsed.timeseries, timeseries_csv)
            self._write_frame(parsed.spot, spot_csv)
            self._write_frame(parsed.forward, forward_csv)

            report = {
                "version_id": version_id,
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "timeseries_rows": len(parsed.timeseries),
                "spot_rows": len(parsed.spot),
                "forward_rows": len(parsed.forward),
            }
            report_json.write_text(json.dumps(report, indent=2), encoding="utf-8")

        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise

        return CurvesPipelineResult(
            version_id=version_id,
            directory=target,
            timeseries_csv=timeseries_csv,
            spot_csv=spot_csv,
            forward_csv=forward_csv,
            report_json=report_json,
        )

    @staticmethod
    def _write_frame(frame: pd.DataFrame, path: Path) -> None:
        if not frame.empty:
            frame.to_csv(path, sep=";", index=False, encoding="utf-8-sig")