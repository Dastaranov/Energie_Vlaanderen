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
from energie_vlaanderen.data.paths import DataPaths, DataPathsError

from energie_vlaanderen.metering.fluvius_csv import FluviusIntervals
from energie_vlaanderen.metering.fluvius_csv import FluviusDataError
from energie_vlaanderen.market.entsoe import EntsoeMarketData

from energie_vlaanderen.ingest.sources import SourceDiscoveryError, VnrSourceScraper
from energie_vlaanderen.ingest.downloader import ArtifactDownloader, DownloadBatch, DownloadedArtifact, DownloadError
from energie_vlaanderen.ingest.raw_store import RawStore, RawStoreError
from energie_vlaanderen.ingest.vtest.pipeline import VTestPipeline, VTestPipelineError

from energie_vlaanderen.domain.models import Profile
from energie_vlaanderen.data.repository import DataRepository
from energie_vlaanderen.calculation.calculator import Calculator

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

'''
def command_profile(args) -> int:
    try:
        config = load_user_config(args.config)
        repository = DataRepository.from_settings()

        resolved = ProfileService(
            repository
        ).build(config)

    except (
        ConfigError,
        FluviusDataError,
        FileNotFoundError,
        ValueError,
    ) as exc:
        print(f"FOUT: {exc}")
        return 2

    usage = resolved.usage

    print("Profiel")
    print("=======")
    print(
        f"Postcode            : "
        f"{config.user.postcode}"
    )
    print(
        f"Gemeente            : "
        f"{config.user.gemeente}"
    )
    print(
        f"Segment             : "
        f"{config.user.segment}"
    )
    print(
        f"DNB elektriciteit   : "
        f"{resolved.dnb_name} "
        f"({resolved.dnb_code})"
    )
    print(
        f"Meter               : "
        f"{config.connection.meter}"
    )
    print(
        f"Fluviusbestand      : "
        f"{usage.source}"
    )
    print(
        f"Meetpunten          : "
        f"{usage.interval_count}"
    )
    print(
        f"Periode vanaf       : "
        f"{usage.start}"
    )
    print(
        f"Periode tot         : "
        f"{usage.end}"
    )
    print(
        f"Afname              : "
        f"{usage.consumption_kwh:.3f} kWh"
    )
    print(
        f"Injectie            : "
        f"{usage.injection_kwh:.3f} kWh"
    )
    print(
        f"Gemiddelde maandpiek: "
        f"{usage.average_monthly_peak_kw:.3f} kW"
    )

    if config.electricity_contract is not None:
        contract = config.electricity_contract

        print()
        print("Huidig elektriciteitscontract")
        print("=============================")
        print(
            f"Leverancier          : "
            f"{contract.supplier}"
        )
        print(
            f"Product              : "
            f"{contract.product}"
        )
        print(
            f"Type                 : "
            f"{contract.kind}"
        )
        print(
            f"Startdatum           : "
            f"{contract.start_date.isoformat()}"
        )

    if usage.warnings:
        print()
        print("Waarschuwingen")
        print("==============")

        for warning in usage.warnings:
            print(f"- {warning}")

    return 0
'''
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
    
    return parser

def run_compare(
    args: argparse.Namespace,
    settings: Settings,
) -> int:
    data_dir = resolve_data_dir(args, settings)

    repository = DataRepository(data_dir)

    if args.validate_sources:
        return run_source_validation(
            args=args,
            data_dir=data_dir,
        )

    profile = Profile(
        postcode=args.postcode,
        gemeente=args.gemeente,
        segment=args.segment,
        meter=args.meter,
        afname_dag_kwh=args.dag,
        afname_nacht_kwh=args.nacht,
        omvormer_kva=args.omvormer_kva,
        geschatte_maandpiek_kw=args.piek,
        kwartier_csv=args.kwartier_csv,
    )

    products = repository.products(
        args.year,
        args.month,
        args.segment,
    )

    intervals = (
        FluviusIntervals.read(args.kwartier_csv)
        if args.kwartier_csv
        else None
    )

    market = load_market_data_if_required(
        args=args,
        settings=settings,
        products=products,
        intervals=intervals,
    )

    calculator = Calculator(
        repository,
        levies_eur_kwh=args.levies_eur_kwh,
        energy_fund_eur_year=args.energy_fund_eur_year,
    )

    rows: list[dict[str, object]] = []

    for product in products:
        try:
            cost = calculator.calculate(
                product,
                profile,
                market,
                intervals,
            )

            rows.append(
                {
                    "leverancier": product.supplier,
                    "product": product.name,
                    "type": product.kind,
                    "energiekost_excl_btw": float(
                        money(cost.supplier)
                    ),
                    "nettarief_excl_btw": float(
                        money(cost.grid)
                    ),
                    "heffingen_excl_btw": float(
                        money(cost.levies)
                    ),
                    "btw": float(money(cost.vat)),
                    "totaal_incl_btw": float(
                        money(cost.total)
                    ),
                    "waarschuwingen": " | ".join(
                        cost.warnings
                    ),
                    "bron": product.source,
                }
            )
        except Exception as exc:
            logging.warning(
                "%s - %s overgeslagen: %s",
                product.supplier,
                product.name,
                exc,
            )

    if not rows:
        logging.error(
            "Geen berekenbare producten gevonden voor "
            "%s-%02d, segment %s.",
            args.year,
            args.month,
            args.segment,
        )
        return 2

    result = pd.DataFrame(rows).sort_values(
        "totaal_incl_btw"
    )

    print(
        result.head(args.top).to_string(
            index=False
        )
    )

    if args.csv:
        output_path = args.csv.expanduser().resolve()
        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        result.to_csv(
            output_path,
            sep=";",
            index=False,
            encoding="utf-8-sig",
            decimal=",",
        )

        logging.info(
            "Resultaten opgeslagen in %s",
            output_path,
        )

    return 0

def load_market_data_if_required(
    *,
    args: argparse.Namespace,
    settings: Settings,
    products: list,
    intervals: pd.DataFrame | None,
) -> pd.DataFrame | None:
    has_dynamic_products = any(
        product.kind.startswith("dynamisch")
        for product in products
    )

    if not has_dynamic_products:
        return None

    paths = DataPaths.from_settings(settings)

    cache_path = (
        args.entsoe_cache.expanduser().resolve()
        if args.entsoe_cache
        else paths.root / "entsoe_day_ahead_prices.json"
    )

    market_data = EntsoeMarketData(
        cache_path,
        args.api_key,
    )

    if intervals is not None and not intervals.empty:
        start = intervals["timestamp"].min().to_pydatetime()
        end = (
            intervals["timestamp"].max()
            + pd.Timedelta(minutes=15)
        ).to_pydatetime()
    else:
        start = datetime(
            args.year,
            args.month,
            1,
        )

        if args.month == 12:
            end = datetime(
                args.year + 1,
                1,
                1,
            )
        else:
            end = datetime(
                args.year,
                args.month + 1,
                1,
            )

    api_key_available = bool(
        args.api_key
        or os.getenv("ENTSOE_API_KEY")
    )

    return market_data.load(
        start,
        end,
        allow_api=api_key_available,
    )

def run_source_validation(
    *,
    args: argparse.Namespace,
    data_dir: Path,
) -> int:
    year = args.year

    electricity_xlsx = (
        data_dir
        / f"Distributienettarieven elektriciteit {year}.xlsx"
    )

    electricity_csv = (
        data_dir
        / f"DNB_ELEK_{year}.csv"
    )

    gas_xlsx = (
        data_dir
        / f"Distributienettarieven aardgas {year}.xlsx"
    )

    gas_csv = (
        data_dir
        / f"DNB_GAS_{year}.csv"
    )

    required_files = (
        electricity_xlsx,
        electricity_csv,
        gas_xlsx,
        gas_csv,
    )

    missing = [
        path
        for path in required_files
        if not path.is_file()
    ]

    if missing:
        logging.error(
            "Bronvalidatie kan niet worden uitgevoerd. "
            "Ontbrekende bestanden:\n%s",
            "\n".join(
                f"  - {path}"
                for path in missing
            ),
        )
        return 2
    '''
    checks = [
        validate_excel_against_csv(
            electricity_xlsx,
            electricity_csv,
            "elektriciteit",
        ),
        validate_excel_against_csv(
            gas_xlsx,
            gas_csv,
            "gas",
        ),
    ]
    
    print(
        json.dumps(
            checks,
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0 if all(
        check["ok"]
        for check in checks
    ) else 2
    '''
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

    try:
        result = VTestPipeline().process(
            source_path=source_path,
            destination=paths.staging / args.version,
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
