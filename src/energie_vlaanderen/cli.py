from __future__ import annotations
import argparse, json, logging, os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import sys
import pandas as pd

# Interne modules
from energie_vlaanderen.settings import Settings
from energie_vlaanderen.utility.constants import D
from energie_vlaanderen.utility.normalizer import money
from energie_vlaanderen.utility.constants import LOCAL_TZ
from energie_vlaanderen.data.paths import DataPaths, DataPathsError

from energie_vlaanderen.metering.fluvius_csv import FluviusIntervals
from energie_vlaanderen.metering.fluvius_csv import FluviusDataError

from energie_vlaanderen.market.entsoe import EntsoeMarketData
from energie_vlaanderen.market.sync import MarketSyncManager, MarketSyncError

from energie_vlaanderen.ingest.sources import SourceDiscoveryError, VnrSourceScraper
from energie_vlaanderen.ingest.downloader import ArtifactDownloader, DownloadBatch, DownloadedArtifact, DownloadError
from energie_vlaanderen.ingest.raw_store import RawStore, RawStoreError
from energie_vlaanderen.ingest.vtest.pipeline import VTestPipeline, VTestPipelineError
from energie_vlaanderen.ingest.tariffs.pipeline import TariffPipeline, TariffPipelineError
from energie_vlaanderen.ingest.curves.pipeline import CurvesPipeline, CurvesPipelineError

from energie_vlaanderen.domain.models import Profile
from energie_vlaanderen.data.repository import DataRepository, DataRepositoryError
from energie_vlaanderen.calculation.calculator import Calculator

from energie_vlaanderen.audit.manager import ApprovalManager, AuditError
from energie_vlaanderen.audit.sanity import SanityChecker
from energie_vlaanderen.audit.sampler import DataSampler
from energie_vlaanderen.audit.golden import VTestGoldenAuditor, TariffGoldenAuditor
from energie_vlaanderen.ingest.vtest.refine_pipeline import VTestRefinePipeline

LOG = logging.getLogger("energievergelijker")

_DB_IMPORT_ERROR = (
    "psycopg / SQLAlchemy / alembic niet geïnstalleerd. "
    "Voer 'pip install -e \".[db]\"' uit."
)

def positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "moet een geheel getal zijn"
        ) from exc

    if number <= 0:
        raise argparse.ArgumentTypeError(
            "moet groter zijn dan nul"
        )

    return number

def run_paths(
    args: argparse.Namespace,
    settings: Settings,
) -> int:
    del args
    return show_paths(settings)

def show_paths(
    settings: Settings | None = None,
) -> int:
    active_settings = settings or Settings.load()

    paths = DataPaths.from_settings(
        active_settings
    )
    paths.ensure()

    print(
        f"Projectroot : "
        f"{active_settings.project_root}"
    )
    print(f"Dataroot    : {paths.root}")
    print(f"Raw         : {paths.raw}")
    print(f"Staging     : {paths.staging}")
    print(f"Versions    : {paths.versions}")
    print(f"Failed      : {paths.failed}")

    try:
        print(
            f"Current     : "
            f"{paths.current_data_dir()}"
        )
    except DataPathsError:
        print("Current     : nog niet ingesteld")

    return 0

def resolve_data_dir(
    args: argparse.Namespace,
    settings: Settings,
) -> Path:
    """
    Gebruik een expliciete --data-map als die werd opgegeven.

    Zonder --data gebruiken we de actieve dataset uit DataPaths.
    """

    if args.data is not None:
        return args.data.expanduser().resolve()

    paths = DataPaths.from_settings(settings)
    return paths.current_data_dir()

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="energievergelijker",
        description="EnergieVergelijker voor Vlaanderen",
    )

    parser.add_argument(
        "--log-level",
        choices=(
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        ),
        default="INFO",
        help="Niveau van logberichten.",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        title="commando's",
    )

    # ---------------------------------------------------------
    # paths
    # ---------------------------------------------------------

    paths_parser = subparsers.add_parser(
        "paths",
        help="Toon de gebruikte configuratie- en datamappen.",
    )

    paths_parser.set_defaults(handler=run_paths)

    # ---------------------------------------------------------
    # sources
    # ---------------------------------------------------------

    sources_parser = subparsers.add_parser(
        "sources",
        help=(
            "Ontdek de actuele officiële "
            "Excelbronnen zonder ze te downloaden."
        ),
    )

    sources_parser.add_argument(
        "--year",
        type=int,
        default=datetime.now().year,
        help="Jaar van de distributienettarieven.",
    )

    sources_parser.add_argument(
        "--json",
        action="store_true",
        help="Geef het resultaat als JSON weer.",
    )
    
    sources_parser.set_defaults(
        handler=run_sources
    )
    
    # ---------------------------------------------------------
    # download
    # ---------------------------------------------------------

    download_parser = subparsers.add_parser(
        "download",
        help=(
            "Ontdek en download de officiële "
            "Excelbronnen naar een nieuwe raw-versie."
        ),
    )

    download_parser.add_argument(
        "--year",
        type=int,
        default=datetime.now().year,
        help="Jaar van de distributienettarieven.",
    )

    download_parser.add_argument(
        "--json",
        action="store_true",
        help="Geef het resultaat als JSON weer.",
    )

    download_parser.set_defaults(
        handler=run_download
    )

    # ---------------------------------------------------------
    # verify-raw
    # ---------------------------------------------------------
    verify_raw_parser = subparsers.add_parser(
        "verify-raw",
        help=(
            "Controleer manifest, bestanden en "
            "checksums van een raw-versie."
        ),
    )

    verify_raw_parser.add_argument(
        "--version",
        required=True,
        help="Raw-versie-id die gecontroleerd wordt.",
    )

    verify_raw_parser.add_argument(
        "--json",
        action="store_true",
        help="Geef het resultaat als JSON weer.",
    )

    verify_raw_parser.set_defaults(
        handler=run_verify_raw
    )

    # ---------------------------------------------------------
    # raw-status
    # ---------------------------------------------------------

    raw_status_parser = subparsers.add_parser(
        "raw-status",
        help=(
            "Toon de lokaal opgeslagen raw-versies "
            "en hun validatiestatus."
        ),
    )

    raw_status_parser.add_argument(
        "--json",
        action="store_true",
        help="Geef het resultaat als JSON weer.",
    )

    raw_status_parser.set_defaults(
        handler=run_raw_status
    )

    # ---------------------------------------------------------
    # parse-vtest
    # ---------------------------------------------------------

    parse_vtest_parser = subparsers.add_parser(
        "parse-vtest",
        help="Verwerk een ruwe V-test Excel via de pipeline naar CSV in de staging map.",
    )

    parse_vtest_parser.add_argument(
        "--version",
        required=True,
        help="Raw-versie-id die verwerkt moet worden.",
    )

    parse_vtest_parser.set_defaults(
        handler=run_parse_vtest
    )

    # ---------------------------------------------------------
    # parse-tariffs
    # ---------------------------------------------------------
    parse_tariffs_parser = subparsers.add_parser(
        "parse-tariffs",
        help="Verwerk een ruwe elektriciteitstarieven Excel via de pipeline naar CSV in de staging map.",
    )
    parse_tariffs_parser.add_argument(
        "--version",
        required=True,
        help="Raw-versie-id die verwerkt moet worden.",
    )
    parse_tariffs_parser.set_defaults(
        handler=run_parse_tariffs
    )

    parse_tariffs_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overschrijf een bestaande tarieven-stagingmap.",
    )
    parse_tariffs_parser.set_defaults(
        handler=run_parse_tariffs
    )

    # ---------------------------------------------------------
    # sync-market
    # ---------------------------------------------------------
    sync_market_parser = subparsers.add_parser(
        "sync-market",
        help="Synchroniseer ENTSO-E marktprijzen voor een opgegeven periode naar de lokale cache.",
    )
    sync_market_parser.add_argument(
        "--start",
        required=True,
        help="Startdatum (formaat: YYYY-MM-DD).",
    )
    sync_market_parser.add_argument(
        "--end",
        required=True,
        help="Einddatum (formaat: YYYY-MM-DD).",
    )
    sync_market_parser.add_argument(
        "--no-api",
        action="store_true",
        help="Gebruik enkel de bestaande lokale cache (geen externe API-aanroepen).",
    )
    sync_market_parser.set_defaults(
        handler=run_sync_market
    )

    # ---------------------------------------------------------
    # parse-curves
    # ---------------------------------------------------------
    parse_curves_parser = subparsers.add_parser(
        "parse-curves",
        help="Verwerk een ruwe energieprijscurves Excel via de pipeline naar CSV in de staging map.",
    )
    parse_curves_parser.add_argument(
        "--version",
        required=True,
        help="Raw-versie-id die verwerkt moet worden.",
    )
    parse_curves_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overschrijf een bestaande curves-stagingmap.",
    )
    parse_curves_parser.set_defaults(
        handler=run_parse_curves
    )

    # ---------------------------------------------------------
    # refine-vtest
    # ---------------------------------------------------------
    refine_vtest_parser = subparsers.add_parser(
        "refine-vtest",
        help="Scrape vtest.be voor contractmetadata (looptijd, datums, links, doelgroep).",
    )
    refine_vtest_parser.add_argument("--version", required=True)
    refine_vtest_parser.add_argument("--postcode", default="9000")
    refine_vtest_parser.add_argument(
        "--no-download",
        action="store_true",
        help="Gebruik bestaande HTML-dump i.p.v. opnieuw te scrapen (vereist geen Selenium).",
    )
    refine_vtest_parser.add_argument(
        "--browser",
        default="chrome",
        choices=("chrome", "firefox"),
        help="Browser voor Selenium (standaard: chrome).",
    )
    refine_vtest_parser.add_argument(
        "--show",
        action="store_true",
        help="Open browser zichtbaar (niet headless).",
    )
    refine_vtest_parser.set_defaults(handler=run_refine_vtest)

    # ---------------------------------------------------------
    # audit-status / approve / set-golden
    # ---------------------------------------------------------
    audit_status_parser = subparsers.add_parser("audit-status", help="Bekijk de audit-status van een versie.")
    audit_status_parser.add_argument("--version", required=True)
    audit_status_parser.set_defaults(handler=run_audit_status)

    audit_approve_parser = subparsers.add_parser("audit-approve", help="Keur een specifieke versie goed.")
    audit_approve_parser.add_argument("--version", required=True)
    audit_approve_parser.add_argument("--notes", default="", help="Optionele notities bij goedkeuring.")
    audit_approve_parser.set_defaults(handler=run_audit_approve)

    set_golden_parser = subparsers.add_parser("set-golden", help="Maak van een goedgekeurde versie de Golden Master.")
    set_golden_parser.add_argument("--version", required=True)
    set_golden_parser.set_defaults(handler=run_set_golden)

    # ---------------------------------------------------------
    # audit-golden
    # ---------------------------------------------------------
    audit_golden_parser = subparsers.add_parser(
        "audit-golden",
        help="Vergelijk gestagede CSVs cel voor cel met de bron-XLSX.",
    )
    audit_golden_parser.add_argument("--version", required=True)
    audit_golden_parser.set_defaults(handler=run_audit_golden)

    # ---------------------------------------------------------
    # audit-sanity
    # ---------------------------------------------------------
    audit_sanity_parser = subparsers.add_parser(
        "audit-sanity", 
        help="Voer de volautomatische business logic checks uit op een versie."
    )
    audit_sanity_parser.add_argument("--version", required=True)
    audit_sanity_parser.set_defaults(handler=run_audit_sanity)

    # ---------------------------------------------------------
    # audit-sample
    # ---------------------------------------------------------
    audit_sample_parser = subparsers.add_parser(
        "audit-sample", 
        help="Neem een willekeurige steekproef uit de data voor visuele menselijke controle."
    )
    audit_sample_parser.add_argument("--version", required=True)
    audit_sample_parser.add_argument(
        "--count", 
        type=int, 
        default=3, 
        help="Aantal rijen per dataset om te controleren (standaard: 3)."
    )
    audit_sample_parser.set_defaults(handler=run_audit_sample)

    # ---------------------------------------------------------
    # db-init
    # ---------------------------------------------------------
    db_init_parser = subparsers.add_parser(
        "db-init",
        help="Maak het databaseschema aan of upgrade het via Alembic-migraties.",
    )
    db_init_parser.set_defaults(handler=run_db_init)

    # ---------------------------------------------------------
    # db-import
    # ---------------------------------------------------------
    db_import_parser = subparsers.add_parser(
        "db-import",
        help="Importeer een gestagede versie (vtest, tarieven, ...) naar de databank.",
    )
    db_import_parser.add_argument("--version", required=True, help="Versie-id om te importeren.")
    db_import_parser.add_argument(
        "--gemeente",
        action="store_true",
        help="Importeer ook DnbPerGemeente.csv (referentiedata — normaal éénmalig).",
    )
    db_import_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Verwijder bestaande rijen van deze versie en herlaad.",
    )
    db_import_parser.set_defaults(handler=run_db_import)

    # ---------------------------------------------------------
    # db-status
    # ---------------------------------------------------------
    db_status_parser = subparsers.add_parser(
        "db-status",
        help="Toon welke versies in de databank staan en hun importstatus.",
    )
    db_status_parser.set_defaults(handler=run_db_status)

    # ---------------------------------------------------------
    # publish
    # ---------------------------------------------------------

    publish_parser = subparsers.add_parser(
        "publish",
        help=(
            "Publiceer een gestagede versie naar de "
            "actieve datarepository."
        ),
    )

    publish_parser.add_argument(
        "--version",
        required=True,
        help="Versie-id van de te publiceren staging-map.",
    )

    publish_parser.add_argument(
        "--keep-staging",
        action="store_true",
        help="Bewaar de staging-map na publicatie (standaard: verwijderen).",
    )

    publish_parser.add_argument(
        "--json",
        action="store_true",
        help="Geef het resultaat als JSON weer.",
    )

    publish_parser.set_defaults(
        handler=run_publish
    )

    return parser

def run_compare(
    args: argparse.Namespace,
    settings: Settings,
) -> int:
    data_dir = resolve_data_dir(args, settings)

    repository = DataRepository(data_dir)

def run_sources(
    args: argparse.Namespace,
    settings: Settings,
) -> int:
    scraper = VnrSourceScraper(settings)

    sources = scraper.discover(
        args.year
    )

    if args.json:
        output = {
            kind: artifact.as_dict()
            for kind, artifact in sources.items()
        }

        print(
            json.dumps(
                output,
                ensure_ascii=False,
                indent=2,
            )
        )

        return 0

    for kind, artifact in sources.items():
        print(kind)
        print(
            f"  bestandsnaam : "
            f"{artifact.filename}"
        )
        print(
            f"  url          : "
            f"{artifact.url}"
        )
        print(
            f"  bronpagina   : "
            f"{artifact.page_url}"
        )
        print()

    return 0

def run_download(
    args: argparse.Namespace,
    settings: Settings,
) -> int:
    paths = DataPaths.from_settings(settings)
    scraper = VnrSourceScraper(settings)
    downloader = ArtifactDownloader(settings)

    sources = scraper.discover(
        args.year
    )

    batch = downloader.download_batch(
        sources=sources,
        paths=paths,
    )

    raw_store = RawStore(paths)

    registration = raw_store.register_batch(
        batch
    )

    if not registration.kept:
        if args.json:
            print(
                json.dumps(
                    {
                        "status": "unchanged",
                        "version_id": (
                            registration.version_id
                        ),
                        "duplicate_of": (
                            registration.duplicate_of
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(
                "Geen nieuwe brondata: inhoud is "
                "identiek aan raw-versie "
                f"{registration.duplicate_of}."
            )

        return 0

    if args.json:
        output = {
            "version_id": batch.version_id,
            "directory": str(batch.directory),
            "manifest": str(batch.manifest_path),
            "artifacts": {
                kind: artifact.as_manifest_dict()
                for kind, artifact
                in batch.artifacts.items()
            },
        }

        print(
            json.dumps(
                output,
                ensure_ascii=False,
                indent=2,
            )
        )

        return 0

    print(
        f"Downloadversie : {batch.version_id}"
    )
    print(
        f"Map             : {batch.directory}"
    )
    print(
        f"Manifest        : {batch.manifest_path}"
    )
    print()

    for kind, artifact in batch.artifacts.items():
        print(kind)
        print(
            f"  bestand       : "
            f"{artifact.stored_filename}"
        )
        print(
            f"  bronnaam      : "
            f"{artifact.original_filename}"
        )
        print(
            f"  grootte       : "
            f"{artifact.size_bytes} bytes"
        )
        print(
            f"  sha256        : "
            f"{artifact.sha256}"
        )
        print()

    return 0

def run_verify_raw(
    args: argparse.Namespace,
    settings: Settings,
) -> int:
    paths = DataPaths.from_settings(
        settings
    )

    store = RawStore(paths)

    report = store.verify(
        args.version
    )

    if args.json:
        print(
            json.dumps(
                {
                    "version_id": report.version_id,
                    "directory": str(
                        report.directory
                    ),
                    "valid": report.valid,
                    "checked_files": (
                        report.checked_files
                    ),
                    "errors": list(
                        report.errors
                    ),
                    "warnings": list(
                        report.warnings
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        return 0 if report.valid else 2

    print(
        f"Raw-versie     : {report.version_id}"
    )
    print(
        f"Map             : {report.directory}"
    )
    print(
        f"Gecontroleerd   : "
        f"{report.checked_files} bestanden"
    )
    print(
        f"Geldig          : "
        f"{'ja' if report.valid else 'nee'}"
    )

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

    return 0 if report.valid else 2

def run_raw_status(
    args: argparse.Namespace,
    settings: Settings,
) -> int:
    paths = DataPaths.from_settings(
        settings
    )

    store = RawStore(paths)
    manifests = store.list_manifests()

    rows: list[dict[str, object]] = []

    for manifest in manifests:
        report = store.verify(
            manifest.version_id
        )

        rows.append(
            {
                "version_id": manifest.version_id,
                "created_at": (
                    manifest.created_at.isoformat()
                ),
                "valid": report.valid,
                "checked_files": (
                    report.checked_files
                ),
                "errors": list(report.errors),
                "warnings": list(
                    report.warnings
                ),
            }
        )

    if args.json:
        print(
            json.dumps(
                rows,
                ensure_ascii=False,
                indent=2,
            )
        )

        return 0

    if not rows:
        print("Geen raw-versies gevonden.")
        return 0

    for row in rows:
        print(row["version_id"])
        print(
            f"  aangemaakt    : "
            f"{row['created_at']}"
        )
        print(
            f"  geldig        : "
            f"{'ja' if row['valid'] else 'nee'}"
        )
        print(
            f"  bestanden     : "
            f"{row['checked_files']}"
        )
        print(
            f"  fouten        : "
            f"{len(row['errors'])}"
        )
        print(
            f"  waarschuwingen: "
            f"{len(row['warnings'])}"
        )
        print()

    return 0

def run_parse_tariffs(
    args: argparse.Namespace,
    settings: Settings,
) -> int:
    """Verifieer een raw-versie en verwerk elektriciteits- en gastarieven naar staging."""
    paths = DataPaths.from_settings(settings)
    store = RawStore(paths)

    raw_report = store.verify(args.version)
    if not raw_report.valid:
        LOG.error("Raw-versie %s is ongeldig.", args.version)
        for error in raw_report.errors:
            LOG.error("%s", error)
        return 2

    manifest_path = raw_report.directory / "manifest.json"
    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOG.error("Manifest is ongeldig: %s", exc)
        return 2

    staging_dest = paths.staging / args.version
    pipeline = TariffPipeline()

    sources = {
        "electricity": "electricity_tariffs",
        "gas": "gas_tariffs",
    }

    for energy_type, artifact_key in sources.items():
        try:
            artifact = manifest_data["artifacts"][artifact_key]
            stored_filename = artifact["stored_filename"]
        except (KeyError, TypeError) as exc:
            LOG.warning("Artifact %r ontbreekt in manifest, overgeslagen: %s", artifact_key, exc)
            continue

        source_path = raw_report.directory / stored_filename
        if not source_path.is_file():
            LOG.error("Tarieven-werkboek niet gevonden: %s", source_path)
            return 2

        try:
            result = pipeline.process(
                source_path=source_path,
                destination=staging_dest,
                version_id=args.version,
                energy_type=energy_type,
                overwrite=args.overwrite,
            )
        except TariffPipelineError as exc:
            LOG.error("Tarievenpipeline [%s] geweigerd: %s", energy_type, exc)
            return 2

        from energie_vlaanderen.ingest.tariffs.normalizer import TariffDataNormalizer
        import json as _json
        try:
            rep = _json.loads(result.report_json.read_text(encoding="utf-8"))
            afname_rows = rep.get("afname_rows", "?")
            injectie_rows = rep.get("injectie_rows", "?")
        except Exception:
            afname_rows = injectie_rows = "?"

        print(f"[{energy_type}] afname: {afname_rows} rijen, injectie: {injectie_rows} rijen → {result.directory}")

    return 0

def run_publish(
    args: argparse.Namespace,
    settings: Settings,
) -> int:
    """Publiceer een gestagede versie naar de actieve datarepository."""
    import shutil

    paths = DataPaths.from_settings(settings)
    version_id = args.version

    # Valideer het versie-id formaat
    try:
        paths.validate_version_id(version_id)
    except DataPathsError as exc:
        LOG.error("%s", exc)
        return 2

    staging_dir = paths.staging / version_id
    if not staging_dir.is_dir():
        LOG.error(
            "Staging-map bestaat niet: %s",
            staging_dir,
        )
        return 2

    vtest_staging = staging_dir / "vtest"
    if not vtest_staging.is_dir():
        LOG.error(
            "V-test stagingmap ontbreekt in %s. "
            "Voer eerst 'parse-vtest --version %s' uit.",
            staging_dir,
            version_id,
        )
        return 2

    version_dir = paths.version_dir(version_id)
    if version_dir.exists():
        LOG.error(
            "Versie-map bestaat al: %s. "
            "Deze versie is mogelijk al gepubliceerd.",
            version_dir,
        )
        return 2

    # Kopieer staging → versions
    try:
        shutil.copytree(staging_dir, version_dir)
    except Exception as exc:
        LOG.error(
            "Kopiëren van staging naar versions mislukt: %s",
            exc,
        )
        shutil.rmtree(version_dir, ignore_errors=True)
        return 2

    # Valideer de kopie via DataRepository
    try:
        DataRepository(version_dir)
    except DataRepositoryError as exc:
        LOG.error(
            "Gepubliceerde versie is ongeldig en werd teruggedraaid: %s",
            exc,
        )
        shutil.rmtree(version_dir, ignore_errors=True)
        return 2

    # Activeer de versie (schrijft current.txt atomisch)
    try:
        paths.activate(version_id)
    except DataPathsError as exc:
        LOG.error(
            "Activatie van versie %s mislukt: %s",
            version_id,
            exc,
        )
        shutil.rmtree(version_dir, ignore_errors=True)
        return 2

    # Ruim staging op (tenzij --keep-staging)
    staging_removed = False
    if not args.keep_staging:
        try:
            shutil.rmtree(staging_dir)
            staging_removed = True
        except Exception as exc:
            LOG.warning(
                "Staging-map kon niet worden verwijderd: %s",
                exc,
            )

    if args.json:
        print(
            json.dumps(
                {
                    "status": "published",
                    "version_id": version_id,
                    "version_dir": str(version_dir),
                    "staging_removed": staging_removed,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(f"Gepubliceerde versie : {version_id}")
    print(f"Versie-map           : {version_dir}")
    print(
        f"Staging verwijderd   : "
        f"{'ja' if staging_removed else 'nee (--keep-staging)'}"
    )
    print(f"Actieve dataset      : {version_dir}")

    return 0

def run_parse_vtest(
    args: argparse.Namespace,
    settings: Settings,
) -> int:
    """Verifieer een raw-versie en verwerk het V-testwerkboek naar staging."""
    paths = DataPaths.from_settings(settings)
    store = RawStore(paths)

    raw_report = store.verify(args.version)
    if not raw_report.valid:
        LOG.error("Raw-versie %s is ongeldig.", args.version)
        for error in raw_report.errors:
            LOG.error("%s", error)
        return 2

    manifest_path = raw_report.directory / "manifest.json"
    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact = manifest_data["artifacts"]["vtest"]
        stored_filename = artifact["stored_filename"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        LOG.error("V-testartifact ontbreekt of manifest is ongeldig: %s", exc)
        return 2

    source_path = raw_report.directory / stored_filename
    if not source_path.is_file():
        LOG.error("V-testwerkboek niet gevonden: %s", source_path)
        return 2

    staging_dest = paths.staging / args.version
    if staging_dest.exists():
        import shutil
        shutil.rmtree(staging_dest, ignore_errors=True)

    try:
        result = VTestPipeline().process(
            source_path=source_path,
            destination=staging_dest,
            version_id=args.version,
        )
    except VTestPipelineError as exc:
        LOG.error("V-testpipeline geweigerd: %s", exc)
        return 2


    print(f"V-test stagingmap       : {result.directory}")
    print(f"Vaste productcomponenten: {result.fixed_rows}")
    print(f"Variabel/dynamisch      : {result.variable_dynamic_rows}")
    print(f"Normalisatiewarnings    : {result.normalization_warnings}")
    print(f"Validatiewarnings       : {result.validation_warnings}")
    print(f"Rapport                  : {result.report_json}")
    return 0

def run_sync_market(
    args: argparse.Namespace,
    settings: Settings,
) -> int:
    from energie_vlaanderen.utility.constants import LOCAL_TZ

    try:
        start_dt = datetime.fromisoformat(args.start).replace(tzinfo=LOCAL_TZ)
        end_dt = datetime.fromisoformat(args.end).replace(tzinfo=LOCAL_TZ)
    except ValueError as exc:
        LOG.error("Ongeldige datumnotatie. Gebruik YYYY-MM-DD: %s", exc)
        return 2

    manager = MarketSyncManager(settings)

    try:
        result = manager.sync_period(
            start=start_dt,
            end=end_dt,
            allow_api=not args.no_api,
        )
    except MarketSyncError as exc:
        LOG.error("Marktsynchronisatie mislukt: %s", exc)
        return 2

    # Zet het absolute pad om naar een leesbaar relatief pad indien mogelijk
    try:
        display_path = result.cache_path.relative_to(settings.project_root)
    except ValueError:
        display_path = result.cache_path

    print(f"Cache-pad       : {display_path}")
    print(f"Periode         : {result.start_date.date()} tot {result.end_date.date()}")
    print(f"Geladen records : {result.records_loaded}")
    print(f"Verwerkt op     : {result.processed_at.isoformat()}")
    return 0

def run_parse_curves(
    args: argparse.Namespace,
    settings: Settings,
) -> int:
    """Verifieer een raw-versie en verwerk het energiecurves werkboek naar staging."""
    paths = DataPaths.from_settings(settings)
    store = RawStore(paths)

    raw_report = store.verify(args.version)
    if not raw_report.valid:
        LOG.error("Raw-versie %s is ongeldig.", args.version)
        for error in raw_report.errors:
            LOG.error("%s", error)
        return 2

    manifest_path = raw_report.directory / "manifest.json"
    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact = manifest_data["artifacts"]["energy_curves"]
        stored_filename = artifact["stored_filename"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        LOG.error("Curvesartifact ontbreekt of manifest is ongeldig: %s", exc)
        return 2

    source_path = raw_report.directory / stored_filename
    if not source_path.is_file():
        LOG.error("Curveswerkboek niet gevonden: %s", source_path)
        return 2

    staging_dest = paths.staging / args.version

    try:
        result = CurvesPipeline().process(
            source_path=source_path,
            destination=staging_dest,
            version_id=args.version,
            overwrite=args.overwrite,
        )
    except CurvesPipelineError as exc:
        LOG.error("Curvespipeline geweigerd: %s", exc)
        return 2

    try:
        display_path = result.directory.relative_to(settings.project_root)
    except ValueError:
        display_path = result.directory

    print(f"Curves stagingmap       : {display_path}")
    print(f"Rapport                 : {result.report_json.name}")
    return 0

def run_audit_golden(args: argparse.Namespace, settings: Settings) -> int:
    """Vergelijk gestagede CSVs cel voor cel met de bron-XLSX."""
    paths = DataPaths.from_settings(settings)
    store = RawStore(paths)
    version_id = args.version

    raw_report = store.verify(version_id)
    if not raw_report.valid:
        LOG.error("Raw-versie %s is ongeldig.", version_id)
        return 2

    manifest_path = raw_report.directory / "manifest.json"
    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOG.error("Manifest is ongeldig: %s", exc)
        return 2

    staging_dir = paths.staging / version_id
    vtest_dir = staging_dir / "vtest"
    tariffs_dir = staging_dir / "tariffs"

    all_results = []

    # --- V-test ---
    try:
        vtest_artifact = manifest_data["artifacts"]["vtest"]
        vtest_xlsx = raw_report.directory / vtest_artifact["stored_filename"]
    except (KeyError, TypeError):
        LOG.warning("V-testartifact ontbreekt in manifest, audit overgeslagen.")
        vtest_xlsx = None

    if vtest_xlsx and vtest_xlsx.is_file():
        auditor = VTestGoldenAuditor()
        for domain, csv_name in [("vtest_vast", "master_vast.csv"), ("vtest_var_dyn", "master_var_dyn.csv")]:
            result = auditor.audit(
                staged_csv=vtest_dir / csv_name,
                source_xlsx=vtest_xlsx,
                domain=domain,
                version_id=version_id,
            )
            all_results.append(result)

    # --- Tarieven ---
    tariff_sources = {
        "electricity": "electricity_tariffs",
        "gas": "gas_tariffs",
    }
    t_auditor = TariffGoldenAuditor()
    for energy_type, artifact_key in tariff_sources.items():
        try:
            artifact = manifest_data["artifacts"][artifact_key]
            xlsx_path = raw_report.directory / artifact["stored_filename"]
        except (KeyError, TypeError):
            LOG.warning("Artifact %r ontbreekt, tarieven audit overgeslagen.", artifact_key)
            continue

        if not xlsx_path.is_file():
            LOG.warning("Tarieven-werkboek niet gevonden: %s", xlsx_path)
            continue

        for direction in ("afname", "injectie"):
            csv_path = tariffs_dir / f"tariffs_{energy_type}_{direction}.csv"
            result = t_auditor.audit(
                staged_csv=csv_path,
                source_xlsx=xlsx_path,
                energy_type=energy_type,
                direction=direction,
                version_id=version_id,
            )
            all_results.append(result)

    if not all_results:
        LOG.error("Geen auditresultaten — is de versie volledig geparsed?")
        return 2

    any_fail = False
    for res in all_results:
        status = "OK " if res.passed else "NOK"
        print(f"{status}  {res.domain:<30} {res.verified_rows}/{res.total_rows} rijen geverifieerd")
        if not res.passed:
            any_fail = True
            for mm in res.mismatches[:10]:
                print(f"      [{mm.field}] {mm.row_key}")
                print(f"        CSV : {mm.csv_value!r}")
                print(f"        XLSX: {mm.xlsx_value!r}")
            if len(res.mismatches) > 10:
                print(f"      ... en {len(res.mismatches) - 10} meer.")

    return 2 if any_fail else 0


def run_audit_status(args: argparse.Namespace, settings: Settings) -> int:
    paths = DataPaths.from_settings(settings)
    manager = ApprovalManager(paths)
    status = manager.get_status(args.version)
    
    print(f"Versie     : {status.version_id}")
    print(f"Status     : {status.status.upper()}")
    print(f"Laatste up : {status.updated_at.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Notities   : {status.notes}")
    
    golden = manager.get_golden_master()
    if golden == args.version:
        print("\n*** DIT IS DE HUIDIGE GOLDEN MASTER ***")
    return 0

def run_audit_approve(args: argparse.Namespace, settings: Settings) -> int:
    paths = DataPaths.from_settings(settings)
    manager = ApprovalManager(paths)
    try:
        manager.approve(args.version, args.notes)
        print(f"Versie {args.version} is nu succesvol goedgekeurd (APPROVED).")
        return 0
    except AuditError as exc:
        LOG.error("Kan niet goedkeuren: %s", exc)
        return 2

def run_set_golden(args: argparse.Namespace, settings: Settings) -> int:
    paths = DataPaths.from_settings(settings)
    manager = ApprovalManager(paths)
    try:
        manager.set_golden_master(args.version)
        print(f"Versie {args.version} is nu de Golden Master.")
        return 0
    except AuditError as exc:
        LOG.error("Fout bij instellen Golden Master: %s", exc)
        return 2

def run_audit_sanity(args: argparse.Namespace, settings: Settings) -> int:
    paths = DataPaths.from_settings(settings)
    checker = SanityChecker(paths)
    
    try:
        report = checker.check_version(args.version)
    except RuntimeError as exc:
        LOG.error("Sanity check mislukt om te starten: %s", exc)
        return 2

    if report.valid:
        print(f"✅ Sanity check GESLAAGD voor versie {args.version}!")
        print("Alle geteste datasets voldoen aan de harde business rules (geen onlogische extremen of onmogelijke waarden gevonden).")
        return 0
    else:
        print(f"❌ Sanity check GEFAALD voor versie {args.version}!")
        print(f"Er zijn {len(report.violations)} schendingen gevonden die kritiek zijn voor een correcte berekening:\n")
        
        for viol in report.violations:
            row_info = f" (rij {viol.row_index})" if viol.row_index is not None else ""
            print(f"  - [{viol.file}{row_info}] RULE '{viol.rule}': {viol.message}")
            
        print("\nDit bestand moet gerepareerd worden (parser of data) voordat de goedkeuring ('audit-approve') kan doorgaan.")
        return 2

def run_audit_sample(args: argparse.Namespace, settings: Settings) -> int:
    paths = DataPaths.from_settings(settings)
    sampler = DataSampler(paths)
    
    try:
        sampler.generate_samples(args.version, args.count)
        return 0
    except RuntimeError as exc:
        LOG.error("Kan steekproef niet genereren: %s", exc)
        return 2

def run_db_init(args: argparse.Namespace, settings: Settings) -> int:
    """Voer Alembic-migraties uit om het schema aan te maken of te upgraden."""
    try:
        from alembic.config import Config
        from alembic import command as alembic_cmd
    except ImportError:
        LOG.error(_DB_IMPORT_ERROR)
        return 2

    alembic_ini = settings.project_root / "db" / "alembic.ini"
    if not alembic_ini.is_file():
        LOG.error("alembic.ini niet gevonden: %s", alembic_ini)
        return 2

    cfg = Config(str(alembic_ini))
    # Overrule de DSN zodat .env geladen wordt
    from energie_vlaanderen.infrastructure.db.connection import get_dsn
    cfg.set_main_option("sqlalchemy.url", get_dsn(settings.project_root))

    alembic_cmd.upgrade(cfg, "head")
    print("Schema is up-to-date.")
    return 0


def run_db_import(args: argparse.Namespace, settings: Settings) -> int:
    """Importeer een gestagede versie naar de databank."""
    try:
        from energie_vlaanderen.infrastructure.db.connection import get_engine
        from energie_vlaanderen.infrastructure.db import importer as imp
        import sqlalchemy as sa
        from sqlalchemy.dialects import postgresql  # noqa: F401 — triggers dialect registration
    except ImportError:
        LOG.error(_DB_IMPORT_ERROR)
        return 2

    paths = DataPaths.from_settings(settings)
    version_id = args.version
    staging_dir = paths.staging / version_id

    if not staging_dir.is_dir():
        LOG.error("Staging-map niet gevonden: %s", staging_dir)
        return 2

    engine = get_engine(settings.project_root)

    with engine.begin() as conn:
        # Controleer dubbele import
        from energie_vlaanderen.infrastructure.db.schema import data_version as dv_table
        existing = conn.execute(
            sa.select(dv_table.c.geimporteerd_op).where(dv_table.c.version_id == version_id)
        ).first()

        if existing and existing[0] is not None and not args.overwrite:
            LOG.error(
                "Versie %s is al geïmporteerd op %s. Gebruik --overwrite om te herladen.",
                version_id, existing[0].strftime("%Y-%m-%d %H:%M")
            )
            return 2

        if existing and args.overwrite:
            # FK-volgorde: kinderen eerst, dan ouders
            conn.execute(sa.text("DELETE FROM vtest_product WHERE version_id = :v"), {"v": version_id})
            conn.execute(sa.text("DELETE FROM vtest_scrape_run WHERE version_id = :v"), {"v": version_id})
            conn.execute(sa.text("DELETE FROM product_component WHERE leverancier_product_id IN "
                                 "(SELECT id FROM leverancier_product WHERE version_id = :v)"), {"v": version_id})
            conn.execute(sa.text("DELETE FROM leverancier_product WHERE version_id = :v"), {"v": version_id})
            conn.execute(sa.text("DELETE FROM netwerk_tarief WHERE version_id = :v"), {"v": version_id})
            LOG.info("Bestaande rijen voor versie %s verwijderd.", version_id)

        # Versiebeheer upsert
        imp.upsert_data_version(conn, version_id)

        results = []

        # Referentiedata gemeente (optioneel)
        if args.gemeente:
            gemeente_csv = settings.data_root / "current" / "DnbPerGemeente.csv"
            if gemeente_csv.is_file():
                r = imp.import_gemeente(conn, gemeente_csv)
                results.append(r)
            else:
                LOG.warning("DnbPerGemeente.csv niet gevonden op %s", gemeente_csv)

        # vtest scrape-run registreren + producten importeren
        vtest_dir = staging_dir / "vtest"
        meta_json = vtest_dir / "vtest_dump_meta.json"
        vtest_csv = vtest_dir / "vtest_products.csv"
        if vtest_csv.is_file():
            scrape_run_id = imp.import_vtest_scrape_run(conn, version_id, meta_json, vtest_dir)
            results.append(imp.import_vtest_products(conn, version_id, vtest_csv, scrape_run_id=scrape_run_id))
        else:
            results.append(imp.import_vtest_products(conn, version_id, vtest_csv))

        # Productcomponenten
        results.append(imp.import_product_components(
            conn,
            vast_csv=vtest_dir / "master_vast.csv",
            var_dyn_csv=vtest_dir / "master_var_dyn.csv",
            version_id=version_id,
        ))

        # Netwerktarieven
        results.append(imp.import_netwerk_tarieven(conn, version_id, staging_dir / "tariffs"))

        # Markeer als geïmporteerd
        imp.mark_imported(conn, version_id)

    for r in results:
        print(f"[{r.domain:<25}] {r.rows_inserted} rijen ingevoegd")
    print(f"Versie {version_id} geïmporteerd.")
    return 0


def run_db_status(args: argparse.Namespace, settings: Settings) -> int:
    """Toon geïmporteerde versies en hun status."""
    try:
        from energie_vlaanderen.infrastructure.db.connection import get_engine
        from energie_vlaanderen.infrastructure.db.schema import data_version as dv_table
        import sqlalchemy as sa
    except ImportError:
        LOG.error(_DB_IMPORT_ERROR)
        return 2

    engine = get_engine(settings.project_root)
    with engine.connect() as conn:
        rows = conn.execute(
            sa.select(
                dv_table.c.version_id,
                dv_table.c.status,
                dv_table.c.geimporteerd_op,
                dv_table.c.aangemaakt_op,
            ).order_by(dv_table.c.version_id.desc())
        ).fetchall()

    if not rows:
        print("Geen versies in de databank.")
        return 0

    for row in rows:
        imp_str = row[2].strftime("%Y-%m-%d %H:%M") if row[2] else "niet geïmporteerd"
        print(f"{row[0]}  {row[1]:<10}  {imp_str}")
    return 0


def run_refine_vtest(args: argparse.Namespace, settings: Settings) -> int:
    """Scrape vtest.be en schrijf contractmetadata naar staging."""
    from energie_vlaanderen.ingest.vtest.html_downloader import VTestDownloadError

    paths = DataPaths.from_settings(settings)
    staging_dir = paths.staging / args.version

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
        LOG.error("Download mislukt: %s", exc)
        return 2
    except FileNotFoundError as exc:
        LOG.error("%s", exc)
        return 2

    elek = sum(1 for _ in open(result.products_csv, encoding="utf-8-sig") if "Elektriciteit" in _)
    gas = sum(1 for _ in open(result.products_csv, encoding="utf-8-sig") if ";Gas;" in _)

    print(f"Scraped at     : {result.scraped_at.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Producten      : {result.products_found} ({elek - 1} elektriciteit, {gas} gas)")
    print(f"CSV            : {result.products_csv}")
    print(f"HTML dump      : {result.dump_html}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(
            logging,
            args.log_level,
        ),
        format="%(levelname)s %(message)s",
    )

    try:
        settings = Settings.load()

        return args.handler(
            args,
            settings,
        )
    except (
        DataPathsError,
        DataRepositoryError,
        FileNotFoundError,
        SourceDiscoveryError,
        ValueError,
        DownloadError,
        RawStoreError,
    ) as exc:
        logging.error("%s", exc)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
