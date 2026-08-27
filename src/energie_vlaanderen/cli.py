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

LOG = logging.getLogger("energievergelijker")

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
    # audit-sanity
    # ---------------------------------------------------------
    audit_sanity_parser = subparsers.add_parser(
        "audit-sanity", 
        help="Voer de volautomatische business logic checks uit op een versie."
    )
    audit_sanity_parser.add_argument("--version", required=True)
    audit_sanity_parser.set_defaults(handler=run_audit_sanity)

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
    """Verifieer een raw-versie en verwerk het tarievenwerkboek naar staging."""
    paths = DataPaths.from_settings(settings)
    store = RawStore(paths)

    # Controleer of we die versie eigenlijk wel in huis hebben gedownload
    raw_report = store.verify(args.version)
    if not raw_report.valid:
        LOG.error("Raw-versie %s is ongeldig.", args.version)
        for error in raw_report.errors:
            LOG.error("%s", error)
        return 2

    manifest_path = raw_report.directory / "manifest.json"
    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        # We halen het bestand "electricity_tariffs" op, want zo hebben we dat benoemd in de downloader
        artifact = manifest_data["artifacts"]["electricity_tariffs"]
        stored_filename = artifact["stored_filename"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        LOG.error("Tarievenartifact ontbreekt of manifest is ongeldig: %s", exc)
        return 2

    source_path = raw_report.directory / stored_filename
    if not source_path.is_file():
        LOG.error("Tarievenwerkboek niet gevonden: %s", source_path)
        return 2

    # Doelmap aanmaken (het is niet ongebruikelijk dat we dezelfde staging map gebruiken als voor vtest)
    staging_dest = paths.staging / args.version

    try:
        # Hier roepen we jouw kersverse pipeline aan!
        result = TariffPipeline().process(
            source_path=source_path,
            destination=staging_dest,
            version_id=args.version,
            overwrite=args.overwrite
        )
    except TariffPipelineError as exc:
        LOG.error("Tarievenpipeline geweigerd: %s", exc)
        return 2

    print(f"Tarieven stagingmap       : {result.directory}")
    print(f"Rapport                   : {result.report_json}")
    
    # Optioneel kan je hier uit je JSON rapport de specifieke info halen (rows afname/injectie) 
    # en naar het scherm printen, net zoals bij de V-test.
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
