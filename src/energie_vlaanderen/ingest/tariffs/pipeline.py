from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from energie_vlaanderen.ingest.tariffs.normalizer import TariffDataNormalizer
from energie_vlaanderen.ingest.tariffs.validator import TariffDataValidator
from energie_vlaanderen.ingest.tariffs.workbook import TariffWorkbookParser


class TariffPipelineError(RuntimeError):
    pass


@dataclass(frozen=True)
class TariffPipelineResult:
    version_id: str
    energy_type: str
    directory: Path
    afname_csv: Path
    injectie_csv: Path
    report_json: Path
    hoogspanning_csv: Path | None = None


class TariffPipeline:
    # Klanttypes die naar de aparte hoogspanning/middenspanning-CSV gaan
    # i.p.v. naar de gewone afname/injectie-CSV's (enkel elektriciteit; gas
    # kent geen HS/MS-equivalent).
    HS_MS_KLANTTYPES = frozenset({"ELEK_HS1", "ELEK_HS2", "ELEK_MS1", "ELEK_MS2", "ELEK_LS_DC"})

    def __init__(self) -> None:
        self.workbook_parser = TariffWorkbookParser()
        self.normalizer = TariffDataNormalizer()
        self.validator = TariffDataValidator()

    def process(
        self,
        source_path: Path,
        destination: Path,
        version_id: str,
        energy_type: str = "electricity",
        overwrite: bool = False,
        tarief_jaar: int | None = None,
    ) -> TariffPipelineResult:
        parsed = self.workbook_parser.parse(source_path, energy_type=energy_type)
        normalized = self.normalizer.normalize(
            parsed.afname, parsed.injectie, parsed.kolomkaarten()
        )
        validation = self.validator.validate(normalized.afname, normalized.injectie)

        if normalized.errors or not validation.valid:
            raise TariffPipelineError("Tariefdata bevat blokkerende fouten en werd niet geëxporteerd.")

        target = destination / "tariffs"
        afname_csv = target / f"tariffs_{energy_type}_afname.csv"
        injectie_csv = target / f"tariffs_{energy_type}_injectie.csv"
        report_json = target / f"tariffs_{energy_type}_report.json"

        hoogspanning_csv: Path | None = None
        afname_out, injectie_out = normalized.afname, normalized.injectie
        hoogspanning_out = pd.DataFrame()

        if energy_type == "electricity":
            hoogspanning_csv = target / "tariffs_electricity_hoogspanning.csv"
            hoogspanning_out, afname_out, injectie_out = self._split_hoogspanning(
                normalized.afname, normalized.injectie
            )

        outputs = [afname_csv, injectie_csv] + ([hoogspanning_csv] if hoogspanning_csv else [])

        if not overwrite:
            existing = [f for f in outputs if f.exists()]
            if existing:
                raise TariffPipelineError(
                    f"Tarieven voor {energy_type} bestaan al in {target}. "
                    "Gebruik --overwrite om deze te overschrijven."
                )

        target.mkdir(parents=True, exist_ok=True)

        # Naar tijdelijke bestanden, en pas omwisselen als alles gelukt is.
        # Met `--overwrite` werden de bestaande CSV's eerder meteen overschreven
        # en bij een fout halverwege ook nog opgeruimd: een schrijffout op het
        # derde bestand kostte dan ook de twee geldige die er al stonden.
        wissels: list[tuple[Path, Path]] = []
        try:
            for frame, doel in (
                (afname_out, afname_csv),
                (injectie_out, injectie_csv),
                *(((hoogspanning_out, hoogspanning_csv),) if hoogspanning_csv else ()),
            ):
                tijdelijk = doel.with_suffix(doel.suffix + ".tijdelijk")
                self._write_frame(frame, tijdelijk)
                wissels.append((tijdelijk, doel))

            report = {
                "version_id": version_id,
                "energy_type": energy_type,
                # Het jaar waarvoor deze tarieven gelden, uit de oorspronkelijke
                # bestandsnaam van het werkboek. Zonder dit veld leidt de
                # databankimport het jaar af uit het versie-id, en dat is het
                # moment van downloaden — niet het tariefjaar.
                "tarief_jaar": tarief_jaar,
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "afname_rows": len(afname_out),
                "injectie_rows": len(injectie_out),
            }
            if hoogspanning_csv is not None:
                report["hoogspanning_rows"] = len(hoogspanning_out)
            tmp_report = report_json.with_suffix(report_json.suffix + ".tijdelijk")
            tmp_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
            wissels.append((tmp_report, report_json))

            # Alles is geschreven; nu pas op hun plaats.
            for bron, doel in wissels:
                os.replace(bron, doel)

        except Exception:
            # Alleen de tijdelijke bestanden. Wat er al stond -- van een vorige,
            # geslaagde run -- blijft ongemoeid.
            for bron, _ in wissels:
                bron.unlink(missing_ok=True)
            raise

        return TariffPipelineResult(
            version_id=version_id,
            energy_type=energy_type,
            directory=target,
            afname_csv=afname_csv,
            injectie_csv=injectie_csv,
            report_json=report_json,
            hoogspanning_csv=hoogspanning_csv,
        )

    @classmethod
    def _split_hoogspanning(
        cls, afname: pd.DataFrame, injectie: pd.DataFrame
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Splits afname/injectie in een hoogspanning/middenspanning-deel
        (ELEK_HS1/HS2/MS1/MS2/LS_DC) en een laagspanning-deel (de rest)."""

        def _mask(frame: pd.DataFrame) -> pd.Series:
            return frame["Klanttype"].isin(cls.HS_MS_KLANTTYPES)

        if afname.empty:
            afname_hs, afname_ls = pd.DataFrame(), afname
        else:
            mask = _mask(afname)
            afname_hs, afname_ls = afname[mask], afname[~mask].reset_index(drop=True)

        if injectie.empty:
            injectie_hs, injectie_ls = pd.DataFrame(), injectie
        else:
            mask = _mask(injectie)
            injectie_hs, injectie_ls = injectie[mask], injectie[~mask].reset_index(drop=True)

        if afname_hs.empty and injectie_hs.empty:
            hoogspanning = pd.DataFrame()
        else:
            hoogspanning = pd.concat([afname_hs, injectie_hs], ignore_index=True)

        return hoogspanning, afname_ls, injectie_ls

    @staticmethod
    def _write_frame(frame: pd.DataFrame, path: Path) -> None:
        frame.to_csv(path, sep=";", index=False, encoding="utf-8-sig")
