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
    verdachte_combinaties: tuple[str, ...] = ()


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
        met_contractdetails: bool = False,
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

        # Eén verzameling over de hele matrix heen: de tariefkaart- en
        # voorwaardenlinks zijn producteigenschappen en verschillen niet per
        # postcode. Dezelfde contracten komen bij elke postcode terug, dus
        # delen scheelt honderden kliks.
        contractdetails: dict[str, dict[str, str]] | None = (
            {} if met_contractdetails else None
        )

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
                    contractdetails=contractdetails,
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

        verdacht = self._verdachte_combinaties(
            geslaagd, self.verwachte_aantallen(staging_dir / "vtest")
        )
        for melding in verdacht:
            LOG.warning("Mogelijk onvolledig: %s", melding)

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
            verdachte_combinaties=tuple(verdacht),
        )

    @staticmethod
    def verwachte_aantallen(vtest_dir: Path) -> dict[tuple[str, str], int]:
        """Hoeveel producten de bulk-export voor de laatste maand kent.

        De scrape en de export zijn twee onafhankelijke bronnen voor dezelfde
        markt, dus de export geeft een absolute ondergrens waar de onderlinge
        vergelijking van postcodes er geen heeft. Dat verschil telt: bij de run
        van 2026-09-01 waren álle acht onderneming/gas-combinaties afgekapt tot
        10 producten terwijl de export er 66 actief telt — uniform, dus
        onderling vergelijken zag niets.

        Geeft een lege dict als de master-CSV's er nog niet zijn; de
        matrixrun mag daar niet op stuklopen.
        """
        rijen: list[dict[str, str]] = []
        for naam in ("master_vast.csv", "master_var_dyn.csv"):
            pad = vtest_dir / naam
            if not pad.is_file():
                continue
            try:
                frame = pd.read_csv(pad, sep=";", dtype=str, encoding="utf-8-sig")
            except (OSError, ValueError, pd.errors.ParserError) as exc:
                LOG.warning("Kon %s niet lezen voor de volledigheidscontrole: %s", naam, exc)
                continue
            rijen.extend(frame.fillna("").to_dict("records"))

        if not rijen:
            return {}

        def periode(rij: dict[str, str]) -> tuple[int, int]:
            try:
                return int(rij.get("year") or 0), int(rij.get("month") or 0)
            except ValueError:
                return 0, 0

        laatste = max(periode(r) for r in rijen)
        per_groep: dict[tuple[str, str], set] = {}
        for rij in rijen:
            if periode(rij) != laatste or rij.get("direction") != "Afname":
                continue
            sleutel = (
                (rij.get("segment") or "").lower(),
                (rij.get("energy") or "").lower(),
            )
            per_groep.setdefault(sleutel, set()).add(
                (rij.get("supplier"), rij.get("product"), rij.get("product_type"))
            )
        return {k: len(v) for k, v in per_groep.items()}

    @staticmethod
    def _verdachte_combinaties(
        resultaten: list[VTestRefinePipelineResult],
        verwacht: dict[tuple[str, str], int] | None = None,
    ) -> list[str]:
        """Meld combinaties die veel minder producten opleverden dan hun buren.

        vtest.be laadt de resultatenlijst lui bij. Stopt het scrollen te vroeg,
        dan levert de combinatie een afgekapte lijst op — zonder dat er iets
        misgaat: de run "slaagt" en de matrix meldt 32/32. Bij de run van
        2026-09-01 gaven zeven van de acht onderneming/elektriciteit-postcodes
        precies 20 producten tegenover 97 bij de achtste.

        Het aanbod verschilt nauwelijks per netbeheerder — gemeten over de
        volledige matrix waren 120 van de 123 woningcontracten in alle acht
        postcodes aanwezig — dus een combinatie die er veel minder oplevert dan
        de mediaan van haar groep is verdacht, niet regionaal.
        """
        per_groep: dict[tuple[str, str], list[VTestRefinePipelineResult]] = {}
        for resultaat in resultaten:
            per_groep.setdefault((resultaat.segment, resultaat.energy), []).append(
                resultaat
            )

        verwacht = verwacht or {}
        meldingen: list[str] = []

        # Eerst de absolute toets: de bulk-export weet onafhankelijk van de
        # scrape hoeveel producten er zijn. Zonder die maatstaf blijft een
        # groep die in haar geheel afgekapt is onzichtbaar.
        for (segment, energy), groep in sorted(per_groep.items()):
            drempel = verwacht.get((segment, energy))
            if not drempel:
                continue
            hoogste = max(r.products_found for r in groep)
            # 60% van de export: de twee bronnen tellen niet identiek — bij de
            # gezonde combinaties lag de scrape op 93 tot 100% — maar een
            # afgekapte lijst zit er ver onder (15 tot 19%).
            if hoogste < drempel * 0.6:
                meldingen.append(
                    f"{segment}/{energy}: hoogstens {hoogste} producten "
                    f"gescrapet terwijl de bulk-export er {drempel} actief "
                    "telt — de resultatenlijst is vermoedelijk in álle "
                    "postcodes afgekapt."
                )

        for (segment, energy), groep in sorted(per_groep.items()):
            if len(groep) < 3:
                continue
            # Afzetten tegen het hoogste aantal, niet tegen de mediaan. Bij de
            # run van 2026-09-01 waren zeven van de acht combinaties afgekapt;
            # de mediaan volgde dan de fout en verklaarde de énige volledige
            # run tot uitschieter. Omdat het aanbod nauwelijks per netbeheerder
            # verschilt, is het hoogste aantal de beste schatting van wat er
            # werkelijk te halen viel.
            hoogste = max(r.products_found for r in groep)
            if hoogste == 0:
                continue
            for resultaat in groep:
                if resultaat.products_found < hoogste * 0.75:
                    meldingen.append(
                        f"{segment}/{energy}/{resultaat.postcode}: "
                        f"{resultaat.products_found} producten tegenover "
                        f"{hoogste} bij de best geladen postcode in deze groep "
                        "— de resultatenlijst is vermoedelijk niet volledig "
                        "ingeladen."
                    )
        return meldingen

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
