from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from energie_vlaanderen.ingest.vtest.html_downloader import VTestHtmlDownloader
from energie_vlaanderen.ingest.vtest.product_normalizer import (
    NormalizedVTestProduct,
    VTestProductNormalizer,
)
from energie_vlaanderen.ingest.vtest.product_parser import VTestProductParser
from energie_vlaanderen.utility.constants import LOCAL_TZ

LOG = logging.getLogger(__name__)

_CSV_COLUMNS = [
    "vreg_id", "supplier_raw", "product_raw", "energy", "tariff_type",
    "looptijd_tekst", "looptijd_maanden",
    "datum_intekenen_van", "datum_intekenen_tot",
    "datum_start_levering_van", "datum_start_levering_tot",
    "doelgroep_zonnepanelen", "doelgroep_ev", "doelgroep_energiedelen",
    "doelgroep_leegstand", "doelgroep_groepsaankoop",
    "prijszekerheid_termijn",
    "prijs_indicatie_eur",
    "link_tariefkaart", "link_voorwaarden", "link_supplier",
    "scraped_at",
]


@dataclass(frozen=True)
class VTestRefinePipelineResult:
    version_id: str
    directory: Path
    products_csv: Path
    dump_html: Path
    products_found: int
    scraped_at: datetime


class VTestRefinePipeline:
    """Scrapes vtest.be en verrijkt de staging-data met contractmetadata."""

    def process(
        self,
        staging_dir: Path,
        version_id: str,
        postcode: str = "9000",
        headless: bool = True,
        browser: str = "chrome",
        timeout: int = 60,
        skip_download: bool = False,
    ) -> VTestRefinePipelineResult:
        vtest_dir = staging_dir / "vtest"
        vtest_dir.mkdir(parents=True, exist_ok=True)

        dump_html = vtest_dir / "vtest_dump.html"
        dump_meta = vtest_dir / "vtest_dump_meta.json"

        if skip_download:
            if not dump_html.is_file():
                raise FileNotFoundError(
                    f"--no-download opgegeven maar geen dump gevonden op {dump_html}"
                )
            LOG.info("Hergebruik bestaande dump: %s", dump_html)
            meta = json.loads(dump_meta.read_text(encoding="utf-8")) if dump_meta.is_file() else {}
            raw_ts = meta.get("scraped_at")
            scraped_at = (
                datetime.fromisoformat(raw_ts) if raw_ts else datetime.now(tz=LOCAL_TZ)
            )
            html = dump_html.read_text(encoding="utf-8")
        else:
            scraped_at = datetime.now(tz=LOCAL_TZ)
            LOG.info("Start HTML-download van vtest.be ...")
            html = VTestHtmlDownloader().download(
                postcode=postcode,
                headless=headless,
                browser=browser,
                timeout=timeout,
            )
            dump_html.write_text(html, encoding="utf-8")
            dump_meta.write_text(
                json.dumps({
                    "postcode": postcode,
                    "scraped_at": scraped_at.isoformat(),
                    "browser": browser,
                    "headless": headless,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            LOG.info("Dump opgeslagen: %s", dump_html)

        LOG.info("HTML parsen ...")
        raw_products = VTestProductParser().parse(html)
        LOG.info("%d producten gevonden.", len(raw_products))

        normalized = VTestProductNormalizer().normalize(raw_products, scraped_at)

        products_csv = vtest_dir / "vtest_products.csv"
        self._write_csv(normalized, products_csv)
        LOG.info("CSV geschreven: %s (%d rijen)", products_csv, len(normalized))

        # Voeg products_found toe aan meta zodat de DB-import het kan lezen
        if dump_meta.is_file():
            try:
                meta = json.loads(dump_meta.read_text(encoding="utf-8"))
                meta["products_found"] = len(normalized)
                dump_meta.write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass

        return VTestRefinePipelineResult(
            version_id=version_id,
            directory=vtest_dir,
            products_csv=products_csv,
            dump_html=dump_html,
            products_found=len(normalized),
            scraped_at=scraped_at,
        )

    @staticmethod
    def _write_csv(products: list[NormalizedVTestProduct], path: Path) -> None:
        rows = []
        for p in products:
            rows.append({
                "vreg_id": p.vreg_id,
                "supplier_raw": p.supplier_raw,
                "product_raw": p.product_raw,
                "energy": p.energy,
                "tariff_type": p.tariff_type,
                "looptijd_tekst": p.looptijd_tekst,
                "looptijd_maanden": "" if p.looptijd_maanden is None else p.looptijd_maanden,
                "datum_intekenen_van": "" if p.datum_intekenen_van is None else p.datum_intekenen_van.isoformat(),
                "datum_intekenen_tot": "" if p.datum_intekenen_tot is None else p.datum_intekenen_tot.isoformat(),
                "datum_start_levering_van": "" if p.datum_start_levering_van is None else p.datum_start_levering_van.isoformat(),
                "datum_start_levering_tot": "" if p.datum_start_levering_tot is None else p.datum_start_levering_tot.isoformat(),
                "doelgroep_zonnepanelen": p.doelgroep_zonnepanelen,
                "doelgroep_ev": p.doelgroep_ev,
                "doelgroep_energiedelen": p.doelgroep_energiedelen,
                "doelgroep_leegstand": p.doelgroep_leegstand,
                "doelgroep_groepsaankoop": p.doelgroep_groepsaankoop,
                "prijszekerheid_termijn": p.prijszekerheid_termijn,
                "prijs_indicatie_eur": "" if p.prijs_indicatie_eur is None else str(p.prijs_indicatie_eur),
                "link_tariefkaart": p.link_tariefkaart,
                "link_voorwaarden": p.link_voorwaarden,
                "link_supplier": p.link_supplier,
                "scraped_at": p.scraped_at.isoformat(),
            })
        df = pd.DataFrame(rows, columns=_CSV_COLUMNS)
        df.to_csv(path, sep=";", index=False, encoding="utf-8-sig")
