"""Draait VTestRefinePipeline over alle (segment, energie, DNB-postcode)-
combinaties — standaard 2 segmenten x 2 energietypes x 8 DNB's = 32 runs.

Elke combinatie wordt onafhankelijk geprobeerd: één mislukte combinatie mag
de andere 31 niet blokkeren (manifest.md §12 — fouten zichtbaar maken,
niet stil laten vallen of alles laten crashen). Tussen combinaties zit een
beleefde pauze, uit respect voor vtest.be (een publieke overheidsdienst).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from energie_vlaanderen.ingest.vtest.refine_pipeline import (
    VTestRefinePipeline,
    VTestRefinePipelineResult,
)

LOG = logging.getLogger(__name__)

DEFAULT_SEGMENTEN = ("woning", "onderneming")
DEFAULT_ENERGIEN = ("elektriciteit", "gas")
DEFAULT_PAUZE_SECONDEN = 3.0


@dataclass(frozen=True)
class VTestMatrixFout:
    segment: str
    energy: str
    dnb_code: str
    postcode: str
    fout: str


@dataclass(frozen=True)
class VTestRefineMatrixResult:
    version_id: str
    combinaties_totaal: int
    combinaties_geslaagd: int
    fouten: tuple[VTestMatrixFout, ...]
    products_csv: Path
    components_csv: Path
    totaal_producten: int


def representatieve_postcodes(dnb_csv_path: Path) -> dict[str, str]:
    """Eén representatieve postcode per unieke DNB Elektriciteit, uit
    data/current/DnbPerGemeente.csv (zelfde bestand als
    infrastructure/db/importer.py::import_gemeente gebruikt)."""
    df = pd.read_csv(dnb_csv_path, sep=";", encoding="utf-8-sig", dtype=str)
    df = df.dropna(subset=["DNB Elektriciteit", "Postcode"])
    postcodes: dict[str, str] = {}
    for _, row in df.iterrows():
        code = row["DNB Elektriciteit"].strip()
        if code and code not in postcodes:
            postcodes[code] = row["Postcode"].strip()
    return postcodes


class VTestRefineMatrix:
    def __init__(self, pipeline: VTestRefinePipeline | None = None) -> None:
        self.pipeline = pipeline or VTestRefinePipeline()

    def run(
        self,
        staging_dir: Path,
        version_id: str,
        dnb_csv_path: Path,
        segments: tuple[str, ...] = DEFAULT_SEGMENTEN,
        energies: tuple[str, ...] = DEFAULT_ENERGIEN,
        postcodes: dict[str, str] | None = None,
        kwh_elektriciteit: int = 15000,
        kwh_gas: int = 10000,
        headless: bool = True,
        browser: str = "chrome",
        timeout: int = 60,
        pause_seconds: float = DEFAULT_PAUZE_SECONDEN,
    ) -> VTestRefineMatrixResult:
        postcodes = postcodes or representatieve_postcodes(dnb_csv_path)

        combinaties = [
            (segment, energy, dnb_code, postcode)
            for segment in segments
            for energy in energies
            for dnb_code, postcode in postcodes.items()
        ]
        LOG.info("Matrix: %d combinaties (segment x energie x DNB).", len(combinaties))

        # Detecteer bestaande per-combinatie bestanden om resume mogelijk te maken
        geslaagd: list[VTestRefinePipelineResult] = []
        fouten: list[VTestMatrixFout] = []
        overgeslagen = 0

        for i, (segment, energy, dnb_code, postcode) in enumerate(combinaties):
            stem = f"{segment}_{energy}_{postcode}"
            vtest_dir = staging_dir / "vtest"
            products_csv = vtest_dir / f"vtest_products_{stem}.csv"

            # Skip als al eerder succesvol gedaan
            if products_csv.is_file():
                LOG.info(
                    "[%d/%d] segment=%s energie=%s dnb=%s postcode=%s (al gedaan, overgeslagen)",
                    i + 1, len(combinaties), segment, energy, dnb_code, postcode,
                )
                # Reconstructeer VTestRefinePipelineResult van bestaande bestanden
                components_csv = vtest_dir / f"vtest_product_components_{stem}.csv"
                try:
                    bestaand = pd.read_csv(products_csv, sep=";", encoding="utf-8-sig")
                except (OSError, ValueError, pd.errors.ParserError) as exc:
                    # Onleesbaar bestand: opnieuw scrapen is beter dan de
                    # combinatie stil te laten wegvallen uit de matrix.
                    LOG.warning(
                        "Bestaande %s niet leesbaar (%s) — combinatie wordt opnieuw gescrapet.",
                        products_csv.name, exc,
                    )
                else:
                    geslaagd.append(
                        VTestRefinePipelineResult(
                            version_id=version_id,
                            directory=vtest_dir,
                            segment=segment,
                            energy=energy,
                            postcode=postcode,
                            products_csv=products_csv,
                            components_csv=components_csv,
                            dump_html=vtest_dir / f"vtest_dump_{stem}.html",
                            products_found=len(bestaand),
                            scraped_at=datetime.now(timezone.utc),
                        )
                    )
                    overgeslagen += 1
                    continue

            LOG.info(
                "[%d/%d] segment=%s energie=%s dnb=%s postcode=%s ...",
                i + 1, len(combinaties), segment, energy, dnb_code, postcode,
            )
            try:
                result = self.pipeline.process(
                    staging_dir=staging_dir,
                    version_id=version_id,
                    postcode=postcode,
                    segment=segment,
                    energy=energy,
                    kwh_elektriciteit=kwh_elektriciteit,
                    kwh_gas=kwh_gas,
                    headless=headless,
                    browser=browser,
                    timeout=timeout,
                )
                geslaagd.append(result)
            except Exception as exc:  # noqa: BLE001 — één mislukte combinatie mag de rest niet blokkeren
                LOG.error(
                    "Combinatie segment=%s energie=%s dnb=%s postcode=%s mislukt: %s",
                    segment, energy, dnb_code, postcode, exc,
                )
                fouten.append(VTestMatrixFout(segment, energy, dnb_code, postcode, str(exc)))

            if i < len(combinaties) - 1:
                time.sleep(pause_seconds)

        vtest_dir = staging_dir / "vtest"
        products_csv, components_csv, totaal = self._merge(vtest_dir, geslaagd)
        self._write_merged_meta(vtest_dir, version_id, len(combinaties), len(geslaagd), fouten, totaal)

        return VTestRefineMatrixResult(
            version_id=version_id,
            combinaties_totaal=len(combinaties),
            combinaties_geslaagd=len(geslaagd),
            fouten=tuple(fouten),
            products_csv=products_csv,
            components_csv=components_csv,
            totaal_producten=totaal,
        )

    @staticmethod
    def _merge(
        vtest_dir: Path, results: list[VTestRefinePipelineResult],
    ) -> tuple[Path, Path, int]:
        products_csv = vtest_dir / "vtest_products.csv"
        components_csv = vtest_dir / "vtest_product_components.csv"

        product_frames = [
            pd.read_csv(r.products_csv, sep=";", encoding="utf-8-sig", dtype=str)
            for r in results if r.products_csv.is_file()
        ]
        component_frames = [
            pd.read_csv(r.components_csv, sep=";", encoding="utf-8-sig", dtype=str)
            for r in results if r.components_csv.is_file()
        ]

        totaal = 0
        if product_frames:
            merged = pd.concat(product_frames, ignore_index=True)
            merged.to_csv(products_csv, sep=";", index=False, encoding="utf-8-sig")
            totaal = len(merged)
        else:
            products_csv.write_text("", encoding="utf-8-sig")

        if component_frames:
            merged_c = pd.concat(component_frames, ignore_index=True)
            merged_c.to_csv(components_csv, sep=";", index=False, encoding="utf-8-sig")
        else:
            components_csv.write_text("", encoding="utf-8-sig")

        return products_csv, components_csv, totaal

    @staticmethod
    def _write_merged_meta(
        vtest_dir: Path,
        version_id: str,
        totaal: int,
        geslaagd: int,
        fouten: list[VTestMatrixFout],
        totaal_producten: int,
    ) -> None:
        """Schrijft een samengevoegde vtest_dump_meta.json (zelfde bestandsnaam
        als een enkelvoudige refine-run) zodat `db import` (die
        import_vtest_scrape_run() op dit bestand baseert) ook na een
        --matrix-run blijft werken."""
        meta_path = vtest_dir / "vtest_dump_meta.json"
        meta_path.write_text(
            json.dumps({
                "matrix": True,
                "version_id": version_id,
                "combinaties_totaal": totaal,
                "combinaties_geslaagd": geslaagd,
                "combinaties_mislukt": len(fouten),
                "products_found": totaal_producten,
                "scraped_at": datetime.now(tz=timezone.utc).isoformat(),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
