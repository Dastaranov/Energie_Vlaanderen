from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from energie_vlaanderen.ingest.vtest.html_downloader import VTestHtmlDownloader
from energie_vlaanderen.ingest.vtest.product_normalizer import (
    NormalizedVTestComponent,
    NormalizedVTestProduct,
    VTestProductNormalizer,
)
from energie_vlaanderen.ingest.vtest.product_parser import VTestProductParser
from energie_vlaanderen.utility.constants import LOCAL_TZ

LOG = logging.getLogger(__name__)

# De detailpanelen worden als losse bestanden bewaard, één per contract, zodat
# een nieuw veld een herparse kost in plaats van een nieuwe scrape. Ze zijn
# producteigenschappen en gelden dus over alle postcodes en segmenten heen —
# vandaar één map per staging-versie en niet per combinatie.
_DETAILS_MAP = "contractdetails"


def _lees_contractdetails(map_pad: Path) -> dict[str, str]:
    """Leest eerder bewaarde detailpanelen van schijf."""
    if not map_pad.is_dir():
        return {}
    fragmenten: dict[str, str] = {}
    for bestand in sorted(map_pad.glob("*.html")):
        try:
            fragmenten[bestand.stem] = bestand.read_text(encoding="utf-8")
        except OSError as exc:
            LOG.warning("Detailpaneel %s niet leesbaar: %s", bestand, exc)
    if fragmenten:
        LOG.info("%d bewaarde detailpanelen ingelezen uit %s", len(fragmenten), map_pad)
    return fragmenten


def _schrijf_contractdetails(map_pad: Path, fragmenten: dict[str, str]) -> int:
    """Bewaart detailpanelen die nog niet op schijf staan."""
    if not fragmenten:
        return 0
    map_pad.mkdir(parents=True, exist_ok=True)
    nieuw = 0
    for vreg_id, html in fragmenten.items():
        if not html:
            continue
        bestand = map_pad / f"{vreg_id}.html"
        if bestand.is_file():
            continue
        bestand.write_text(html, encoding="utf-8")
        nieuw += 1
    if nieuw:
        LOG.info("%d nieuwe detailpanelen bewaard in %s", nieuw, map_pad)
    return nieuw


_PRODUCT_CSV_COLUMNS = [
    "vreg_id", "supplier_raw", "product_raw", "energy", "tariff_type",
    "looptijd_tekst", "looptijd_maanden",
    "datum_intekenen_van", "datum_intekenen_tot",
    "datum_start_levering_van", "datum_start_levering_tot",
    "doelgroep_zonnepanelen", "doelgroep_ev", "doelgroep_energiedelen",
    "doelgroep_leegstand", "doelgroep_groepsaankoop",
    "prijszekerheid_termijn",
    "prijs_indicatie_eur",
    "link_tariefkaart", "link_voorwaarden", "link_supplier",
    "contracttype", "supplier_id", "product_id", "green_type", "stars",
    "complex_product", "grayedout", "discount_eur",
    "total_excl_btw", "total_incl_btw", "btw_bedrag", "totaal_verbruik_kwh",
    "segment", "postcode",
    "scraped_at",
]

_COMPONENT_CSV_COLUMNS = [
    "vreg_id", "groep_naam", "component_id", "component_naam",
    "calculation_type", "totaal_excl_btw", "totaal_incl_btw", "btw_bedrag",
    "btw_percentage", "formule", "segment", "postcode",
]


def _combo_stem(segment: str, energy: str, postcode: str) -> str:
    return f"{segment}_{energy}_{postcode}"


@dataclass(frozen=True)
class VTestRefinePipelineResult:
    version_id: str
    directory: Path
    segment: str
    energy: str
    postcode: str
    products_csv: Path
    components_csv: Path
    dump_html: Path
    products_found: int
    scraped_at: datetime


class VTestRefinePipeline:
    """Scrapes vtest.be voor één (segment, energie, postcode)-combinatie en
    verrijkt de staging-data met contractmetadata + volledige kostenopbouw."""

    def process(
        self,
        staging_dir: Path,
        version_id: str,
        postcode: str = "9000",
        segment: str = "woning",
        energy: str = "elektriciteit",
        kwh_elektriciteit: int = 15000,
        kwh_gas: int = 10000,
        headless: bool = True,
        browser: str = "firefox",
        timeout: int = 60,
        skip_download: bool = False,
        contractdetails: dict[str, str] | None = None,
    ) -> VTestRefinePipelineResult:
        vtest_dir = staging_dir / "vtest"
        vtest_dir.mkdir(parents=True, exist_ok=True)

        stem = _combo_stem(segment, energy, postcode)
        dump_html = vtest_dir / f"vtest_dump_{stem}.html"
        dump_meta = vtest_dir / f"vtest_dump_meta_{stem}.json"

        # Wat al op schijf staat telt mee, ook wanneer er niet om
        # contractdetails gevraagd is: dan blijft een herparse (--no-download)
        # de eerder opgehaalde panelen gebruiken in plaats van ze te negeren.
        details_dir = vtest_dir / _DETAILS_MAP
        bewaarde_details = _lees_contractdetails(details_dir)
        if contractdetails is not None:
            for vreg_id, fragment in bewaarde_details.items():
                contractdetails.setdefault(vreg_id, fragment)

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
            LOG.info(
                "Start HTML-download van vtest.be (segment=%s, energie=%s, postcode=%s) ...",
                segment, energy, postcode,
            )
            html = VTestHtmlDownloader().download(
                contractdetails=contractdetails,
                reeds_gekend=set(contractdetails) if contractdetails else None,
                postcode=postcode,
                segment=segment,
                kwh_elektriciteit=kwh_elektriciteit,
                kwh_gas=kwh_gas,
                energy=energy,
                headless=headless,
                browser=browser,
                timeout=timeout,
            )
            dump_html.write_text(html, encoding="utf-8")
            if contractdetails:
                _schrijf_contractdetails(details_dir, contractdetails)
            dump_meta.write_text(
                json.dumps({
                    "postcode": postcode,
                    "segment": segment,
                    "energy": energy,
                    "scraped_at": scraped_at.isoformat(),
                    "browser": browser,
                    "headless": headless,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            LOG.info("Dump opgeslagen: %s", dump_html)

        # De datums, de doelgroep, de looptijd, de prijszekerheid en de links
        # naar de tariefkaart en de algemene voorwaarden staan niet in de
        # resultatendump maar in het detailpaneel per contract. Die panelen
        # gaan als aparte fragmenten mee de parser in.
        fragmenten = contractdetails if contractdetails is not None else bewaarde_details

        LOG.info("HTML parsen ...")
        raw_products = VTestProductParser().parse(html, detail_fragments=fragmenten)
        LOG.info("%d producten gevonden.", len(raw_products))

        gekoppeld = sum(1 for p in raw_products if p.vreg_id in (fragmenten or {}))
        if gekoppeld == len(raw_products) and raw_products:
            LOG.info("Contractdetails gekoppeld aan alle %d producten.", gekoppeld)
        else:
            # Luid, niet stil: een ontbrekend detailpaneel kost geen fout maar
            # vijftien lege kolommen in vtest_contract, en dat viel eerder pas
            # maanden later op.
            LOG.warning(
                "Contractdetails ontbreken voor %d van %d producten — "
                "intekenperiode, start levering, looptijd, doelgroep, "
                "prijszekerheid en de tariefkaartlink blijven daar leeg.",
                len(raw_products) - gekoppeld, len(raw_products),
            )

        normalizer = VTestProductNormalizer()
        normalized = normalizer.normalize(raw_products, scraped_at)
        components = normalizer.normalize_components(raw_products)

        products_csv = vtest_dir / f"vtest_products_{stem}.csv"
        components_csv = vtest_dir / f"vtest_product_components_{stem}.csv"
        self._write_products_csv(normalized, segment, postcode, products_csv)
        self._write_components_csv(components, segment, postcode, components_csv)
        LOG.info(
            "CSV's geschreven: %s (%d rijen), %s (%d rijen)",
            products_csv, len(normalized), components_csv, len(components),
        )

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
            segment=segment,
            energy=energy,
            postcode=postcode,
            products_csv=products_csv,
            components_csv=components_csv,
            dump_html=dump_html,
            products_found=len(normalized),
            scraped_at=scraped_at,
        )

    @staticmethod
    def _write_products_csv(
        products: list[NormalizedVTestProduct], segment: str, postcode: str, path: Path,
    ) -> None:
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
                "contracttype": p.contracttype,
                "supplier_id": p.supplier_id,
                "product_id": p.product_id,
                "green_type": p.green_type,
                "stars": "" if p.stars is None else p.stars,
                "complex_product": p.complex_product,
                "grayedout": p.grayedout,
                "discount_eur": "" if p.discount_eur is None else str(p.discount_eur),
                "total_excl_btw": "" if p.total_excl_btw is None else str(p.total_excl_btw),
                "total_incl_btw": "" if p.total_incl_btw is None else str(p.total_incl_btw),
                "btw_bedrag": "" if p.btw_bedrag is None else str(p.btw_bedrag),
                "totaal_verbruik_kwh": "" if p.totaal_verbruik_kwh is None else str(p.totaal_verbruik_kwh),
                "segment": segment,
                "postcode": postcode,
                "scraped_at": p.scraped_at.isoformat(),
            })
        df = pd.DataFrame(rows, columns=_PRODUCT_CSV_COLUMNS)
        df.to_csv(path, sep=";", index=False, encoding="utf-8-sig")

    @staticmethod
    def _write_components_csv(
        components: list[NormalizedVTestComponent], segment: str, postcode: str, path: Path,
    ) -> None:
        rows = []
        for c in components:
            rows.append({
                "vreg_id": c.vreg_id,
                "groep_naam": c.groep_naam,
                "component_id": c.component_id,
                "component_naam": c.component_naam,
                "calculation_type": c.calculation_type,
                "totaal_excl_btw": "" if c.totaal_excl_btw is None else str(c.totaal_excl_btw),
                "totaal_incl_btw": "" if c.totaal_incl_btw is None else str(c.totaal_incl_btw),
                "btw_bedrag": "" if c.btw_bedrag is None else str(c.btw_bedrag),
                "btw_percentage": "" if c.btw_percentage is None else str(c.btw_percentage),
                "formule": c.formule,
                "segment": segment,
                "postcode": postcode,
            })
        df = pd.DataFrame(rows, columns=_COMPONENT_CSV_COLUMNS)
        df.to_csv(path, sep=";", index=False, encoding="utf-8-sig")
