"""Ingestcommando's: bronnen ontdekken/downloaden, parsen naar staging, publiceren."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from datetime import datetime

from energie_vlaanderen.cli.helpers import (
    RawVersionError,
    fail,
    relative_or_absolute,
    require_valid_raw_version,
    resolve_artifact,
)
from energie_vlaanderen.cli.output import emit, print_json
from energie_vlaanderen.data.paths import DataPaths, DataPathsError
from energie_vlaanderen.data.repository import DataRepository, DataRepositoryError
from energie_vlaanderen.ingest.curves.pipeline import CurvesPipeline, CurvesPipelineError
from energie_vlaanderen.ingest.downloader import ArtifactDownloader
from energie_vlaanderen.ingest.raw_store import RawStore
from energie_vlaanderen.ingest.sources import VnrSourceScraper
from energie_vlaanderen.ingest.tariffs.pipeline import TariffPipeline, TariffPipelineError
from energie_vlaanderen.ingest.vtest.pipeline import VTestPipeline, VTestPipelineError
from energie_vlaanderen.ingest.vtest.refine_pipeline import VTestRefinePipeline
from energie_vlaanderen.market.sync import MarketSyncError, MarketSyncManager
from energie_vlaanderen.settings import Settings
from energie_vlaanderen.utility.constants import LOCAL_TZ

LOG = logging.getLogger("energievergelijker")


# ---------------------------------------------------------
# sources
# ---------------------------------------------------------

def run_sources(args: argparse.Namespace, settings: Settings) -> int:
    scraper = VnrSourceScraper(settings)
    sources = scraper.discover(args.year)

    def _text() -> None:
        for kind, artifact in sources.items():
            print(kind)
            print(f"  bestandsnaam : {artifact.filename}")
            print(f"  url          : {artifact.url}")
            print(f"  bronpagina   : {artifact.page_url}")
            print()

    emit(
        args,
        text_fn=_text,
        json_obj={kind: artifact.as_dict() for kind, artifact in sources.items()},
    )
    return 0


# ---------------------------------------------------------
# download
# ---------------------------------------------------------

def run_download(args: argparse.Namespace, settings: Settings) -> int:
    paths = DataPaths.from_settings(settings)
    scraper = VnrSourceScraper(settings)
    downloader = ArtifactDownloader(settings)

    LOG.info("Bronnen ontdekken voor jaar %s ...", args.year)
    sources = scraper.discover(args.year)

    LOG.info("%d bron(nen) gevonden, downloaden ...", len(sources))
    batch = downloader.download_batch(sources=sources, paths=paths)

    LOG.info("Download voltooid, registreren in raw store ...")
    raw_store = RawStore(paths)
    registration = raw_store.register_batch(batch)

    if not registration.kept:
        def _unchanged_text() -> None:
            print(
                "Geen nieuwe brondata: inhoud is "
                "identiek aan raw-versie "
                f"{registration.duplicate_of}."
            )

        emit(
            args,
            text_fn=_unchanged_text,
            json_obj={
                "status": "unchanged",
                "version_id": registration.version_id,
                "duplicate_of": registration.duplicate_of,
            },
        )
        return 0

    def _text() -> None:
        print(f"Downloadversie : {batch.version_id}")
        print(f"Map             : {batch.directory}")
        print(f"Manifest        : {batch.manifest_path}")
        print()

        for kind, artifact in batch.artifacts.items():
            print(kind)
            print(f"  bestand       : {artifact.stored_filename}")
            print(f"  bronnaam      : {artifact.original_filename}")
            print(f"  grootte       : {artifact.size_bytes} bytes")
            print(f"  sha256        : {artifact.sha256}")
            print()

    emit(
        args,
        text_fn=_text,
        json_obj={
            "version_id": batch.version_id,
            "directory": str(batch.directory),
            "manifest": str(batch.manifest_path),
            "artifacts": {
                kind: artifact.as_manifest_dict()
                for kind, artifact in batch.artifacts.items()
            },
        },
    )
    return 0


# ---------------------------------------------------------
# verify-raw
# ---------------------------------------------------------

def run_verify_raw(args: argparse.Namespace, settings: Settings) -> int:
    paths = DataPaths.from_settings(settings)
    store = RawStore(paths)
    report = store.verify(args.version)

    def _text() -> None:
        print(f"Raw-versie     : {report.version_id}")
        print(f"Map             : {report.directory}")
        print(f"Gecontroleerd   : {report.checked_files} bestanden")
        print(f"Geldig          : {'ja' if report.valid else 'nee'}")

        if report.warnings:
            print()
            print("Waarschuwingen:")
            for warning in report.warnings:
                print(f"  - {warning}")

        if report.errors:
            print()
            print("Fouten:")
            for error in report.errors:
                print(f"  - {error}")

    emit(
        args,
        text_fn=_text,
        json_obj={
            "version_id": report.version_id,
            "directory": str(report.directory),
            "valid": report.valid,
            "checked_files": report.checked_files,
            "errors": list(report.errors),
            "warnings": list(report.warnings),
        },
    )
    return 0 if report.valid else 2


# ---------------------------------------------------------
# raw-status
# ---------------------------------------------------------

def run_raw_status(args: argparse.Namespace, settings: Settings) -> int:
    paths = DataPaths.from_settings(settings)
    store = RawStore(paths)
    manifests = store.list_manifests()

    rows: list[dict[str, object]] = []
    for manifest in manifests:
        report = store.verify(manifest.version_id)
        rows.append(
            {
                "version_id": manifest.version_id,
                "created_at": manifest.created_at.isoformat(),
                "valid": report.valid,
                "checked_files": report.checked_files,
                "errors": list(report.errors),
                "warnings": list(report.warnings),
            }
        )

    def _text() -> None:
        if not rows:
            print("Geen raw-versies gevonden.")
            return

        for row in rows:
            print(row["version_id"])
            print(f"  aangemaakt    : {row['created_at']}")
            print(f"  geldig        : {'ja' if row['valid'] else 'nee'}")
            print(f"  bestanden     : {row['checked_files']}")
            print(f"  fouten        : {len(row['errors'])}")
            print(f"  waarschuwingen: {len(row['warnings'])}")
            print()

    emit(args, text_fn=_text, json_obj=rows)
    return 0


# ---------------------------------------------------------
# staging parse (combineert parse-vtest / parse-tariffs / parse-curves)
# ---------------------------------------------------------

_STAGING_TARGETS = ("vtest", "tariffs", "curves")


def run_staging_parse(args: argparse.Namespace, settings: Settings) -> int:
    """Verwerk één of meerdere ruwe werkboeken naar staging, via --only."""
    targets = _STAGING_TARGETS if args.only == "all" else (args.only,)

    handlers = {
        "vtest": run_parse_vtest,
        "tariffs": run_parse_tariffs,
        "curves": run_parse_curves,
    }

    overall_rc = 0
    for target in targets:
        rc = handlers[target](args, settings)
        if rc != 0:
            overall_rc = rc

    return overall_rc


# ---------------------------------------------------------
# parse-vtest
# ---------------------------------------------------------

def run_parse_vtest(args: argparse.Namespace, settings: Settings) -> int:
    """Verifieer een raw-versie en verwerk het V-testwerkboek naar staging."""
    paths = DataPaths.from_settings(settings)

    try:
        raw_report, manifest_data = require_valid_raw_version(paths, args.version)
        source_path = resolve_artifact(manifest_data, raw_report, "vtest")
    except RawVersionError as exc:
        return fail("%s", exc)

    staging_dest = paths.staging / args.version
    if staging_dest.exists():
        shutil.rmtree(staging_dest, ignore_errors=True)

    LOG.info("V-testwerkboek verwerken ...")
    try:
        result = VTestPipeline().process(
            source_path=source_path,
            destination=staging_dest,
            version_id=args.version,
        )
    except VTestPipelineError as exc:
        return fail("V-testpipeline geweigerd: %s", exc)

    def _text() -> None:
        print(f"V-test stagingmap       : {result.directory}")
        print(f"Vaste productcomponenten: {result.fixed_rows}")
        print(f"Variabel/dynamisch      : {result.variable_dynamic_rows}")
        print(f"Normalisatiewarnings    : {result.normalization_warnings}")
        print(f"Validatiewarnings       : {result.validation_warnings}")
        print(f"Rapport                  : {result.report_json}")

    emit(
        args,
        text_fn=_text,
        json_obj={
            "directory": str(result.directory),
            "fixed_rows": result.fixed_rows,
            "variable_dynamic_rows": result.variable_dynamic_rows,
            "normalization_warnings": result.normalization_warnings,
            "validation_warnings": result.validation_warnings,
            "report_json": str(result.report_json),
        },
    )
    return 0


# ---------------------------------------------------------
# parse-tariffs
# ---------------------------------------------------------

def run_parse_tariffs(args: argparse.Namespace, settings: Settings) -> int:
    """Verifieer een raw-versie en verwerk elektriciteits- en gastarieven naar staging."""
    paths = DataPaths.from_settings(settings)

    try:
        raw_report, manifest_data = require_valid_raw_version(paths, args.version)
    except RawVersionError as exc:
        return fail("%s", exc)

    staging_dest = paths.staging / args.version
    pipeline = TariffPipeline()

    sources = {
        "electricity": "electricity_tariffs",
        "gas": "gas_tariffs",
    }

    processed: list[dict[str, object]] = []

    for energy_type, artifact_key in sources.items():
        try:
            source_path = resolve_artifact(manifest_data, raw_report, artifact_key)
        except RawVersionError as exc:
            LOG.warning("%s, overgeslagen.", exc)
            continue

        LOG.info("Verwerken van %s tarieven ...", energy_type)
        try:
            result = pipeline.process(
                source_path=source_path,
                destination=staging_dest,
                version_id=args.version,
                energy_type=energy_type,
                overwrite=args.overwrite,
            )
        except TariffPipelineError as exc:
            return fail("Tarievenpipeline [%s] geweigerd: %s", energy_type, exc)

        try:
            report = json.loads(result.report_json.read_text(encoding="utf-8"))
            afname_rows = report.get("afname_rows", "?")
            injectie_rows = report.get("injectie_rows", "?")
        except (OSError, json.JSONDecodeError):
            afname_rows = injectie_rows = "?"

        print(
            f"[{energy_type}] afname: {afname_rows} rijen, "
            f"injectie: {injectie_rows} rijen → {result.directory}"
        )
        processed.append(
            {
                "energy_type": energy_type,
                "directory": str(result.directory),
                "afname_rows": afname_rows,
                "injectie_rows": injectie_rows,
            }
        )

    if args.json:
        print_json(processed)
    return 0


# ---------------------------------------------------------
# parse-curves
# ---------------------------------------------------------

def run_parse_curves(args: argparse.Namespace, settings: Settings) -> int:
    """Verifieer een raw-versie en verwerk het energiecurves werkboek naar staging."""
    paths = DataPaths.from_settings(settings)

    try:
        raw_report, manifest_data = require_valid_raw_version(paths, args.version)
        source_path = resolve_artifact(manifest_data, raw_report, "energy_curves")
    except RawVersionError as exc:
        return fail("%s", exc)

    staging_dest = paths.staging / args.version

    LOG.info("Energiecurves-werkboek verwerken ...")
    try:
        result = CurvesPipeline().process(
            source_path=source_path,
            destination=staging_dest,
            version_id=args.version,
            overwrite=args.overwrite,
        )
    except CurvesPipelineError as exc:
        return fail("Curvespipeline geweigerd: %s", exc)

    display_path = relative_or_absolute(result.directory, settings.project_root)

    def _text() -> None:
        print(f"Curves stagingmap       : {display_path}")
        print(f"Rapport                 : {result.report_json.name}")

    emit(
        args,
        text_fn=_text,
        json_obj={
            "directory": str(display_path),
            "report_json": result.report_json.name,
        },
    )
    return 0


# ---------------------------------------------------------
# refine-vtest
# ---------------------------------------------------------

def run_refine_vtest(args: argparse.Namespace, settings: Settings) -> int:
    """Scrape vtest.be en schrijf contractmetadata naar staging."""
    from energie_vlaanderen.ingest.vtest.html_downloader import VTestDownloadError

    paths = DataPaths.from_settings(settings)
    staging_dir = paths.staging / args.version

    LOG.info("Scrapen van vtest.be voor postcode %s ...", args.postcode)
    try:
        result = VTestRefinePipeline().process(
            staging_dir=staging_dir,
            version_id=args.version,
            postcode=args.postcode,
            headless=not args.show,
            browser=args.browser,
            skip_download=args.no_download,
        )
    except VTestDownloadError as exc:
        return fail("Download mislukt: %s", exc)
    except FileNotFoundError as exc:
        return fail("%s", exc)

    elek = sum(1 for _ in open(result.products_csv, encoding="utf-8-sig") if "Elektriciteit" in _)
    gas = sum(1 for _ in open(result.products_csv, encoding="utf-8-sig") if ";Gas;" in _)

    def _text() -> None:
        print(f"Scraped at     : {result.scraped_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Producten      : {result.products_found} ({elek - 1} elektriciteit, {gas} gas)")
        print(f"CSV            : {result.products_csv}")
        print(f"HTML dump      : {result.dump_html}")

    emit(
        args,
        text_fn=_text,
        json_obj={
            "scraped_at": result.scraped_at.isoformat(),
            "products_found": result.products_found,
            "electricity": elek - 1,
            "gas": gas,
            "products_csv": str(result.products_csv),
            "dump_html": str(result.dump_html),
        },
    )
    return 0


# ---------------------------------------------------------
# sync-market
# ---------------------------------------------------------

def run_sync_market(args: argparse.Namespace, settings: Settings) -> int:
    try:
        start_dt = datetime.fromisoformat(args.start).replace(tzinfo=LOCAL_TZ)
        end_dt = datetime.fromisoformat(args.end).replace(tzinfo=LOCAL_TZ)
    except ValueError as exc:
        return fail("Ongeldige datumnotatie. Gebruik YYYY-MM-DD: %s", exc)

    manager = MarketSyncManager(settings)

    LOG.info(
        "Synchroniseren van marktprijzen %s .. %s ...",
        start_dt.date(),
        end_dt.date(),
    )
    try:
        result = manager.sync_period(
            start=start_dt,
            end=end_dt,
            allow_api=not args.no_api,
        )
    except MarketSyncError as exc:
        return fail("Marktsynchronisatie mislukt: %s", exc)

    display_path = relative_or_absolute(result.cache_path, settings.project_root)

    def _text() -> None:
        print(f"Cache-pad       : {display_path}")
        print(f"Periode         : {result.start_date.date()} tot {result.end_date.date()}")
        print(f"Geladen records : {result.records_loaded}")
        print(f"Verwerkt op     : {result.processed_at.isoformat()}")

    emit(
        args,
        text_fn=_text,
        json_obj={
            "cache_path": str(display_path),
            "start_date": result.start_date.date().isoformat(),
            "end_date": result.end_date.date().isoformat(),
            "records_loaded": result.records_loaded,
            "processed_at": result.processed_at.isoformat(),
        },
    )
    return 0


# ---------------------------------------------------------
# publish
# ---------------------------------------------------------

def run_publish(args: argparse.Namespace, settings: Settings) -> int:
    """Publiceer een gestagede versie naar de actieve datarepository."""
    paths = DataPaths.from_settings(settings)
    version_id = args.version

    try:
        paths.validate_version_id(version_id)
    except DataPathsError as exc:
        return fail("%s", exc)

    staging_dir = paths.staging / version_id
    if not staging_dir.is_dir():
        return fail("Staging-map bestaat niet: %s", staging_dir)

    vtest_staging = staging_dir / "vtest"
    if not vtest_staging.is_dir():
        return fail(
            "De V-testdataset ontbreekt in de stagingmap.\n\n"
            "Voer eerst uit:\n"
            "  energievergelijker staging parse \\\n"
            "      --version %s \\\n"
            "      --only vtest",
            version_id,
        )

    version_dir = paths.version_dir(version_id)
    if version_dir.exists():
        return fail(
            "Versie-map bestaat al: %s. Deze versie is mogelijk al gepubliceerd.",
            version_dir,
        )

    # Kopieer staging → versions
    try:
        shutil.copytree(staging_dir, version_dir)
    except Exception as exc:
        shutil.rmtree(version_dir, ignore_errors=True)
        return fail("Kopiëren van staging naar versions mislukt: %s", exc)

    # Valideer de kopie via DataRepository
    try:
        DataRepository(version_dir)
    except DataRepositoryError as exc:
        shutil.rmtree(version_dir, ignore_errors=True)
        return fail("Gepubliceerde versie is ongeldig en werd teruggedraaid: %s", exc)

    # Activeer de versie (schrijft current.txt atomisch)
    try:
        paths.activate(version_id)
    except DataPathsError as exc:
        shutil.rmtree(version_dir, ignore_errors=True)
        return fail("Activatie van versie %s mislukt: %s", version_id, exc)

    # Ruim staging op (tenzij --keep-staging)
    staging_removed = False
    if not args.keep_staging:
        try:
            shutil.rmtree(staging_dir)
            staging_removed = True
        except Exception as exc:
            LOG.warning("Staging-map kon niet worden verwijderd: %s", exc)

    def _text() -> None:
        print(f"Gepubliceerde versie : {version_id}")
        print(f"Versie-map           : {version_dir}")
        print(
            f"Staging verwijderd   : "
            f"{'ja' if staging_removed else 'nee (--keep-staging)'}"
        )
        print(f"Actieve dataset      : {version_dir}")

    emit(
        args,
        text_fn=_text,
        json_obj={
            "status": "published",
            "version_id": version_id,
            "version_dir": str(version_dir),
            "staging_removed": staging_removed,
        },
    )
    return 0

