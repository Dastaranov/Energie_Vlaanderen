from __future__ import annotations
import argparse, json, logging, os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import sys
import pandas as pd

from .constants import D
from .models import Profile
from .normalizer import money
from .repository import DataRepository
from .calculator import Calculator
from .intervals import FluviusIntervals
from .market import EntsoeMarketData
from .validation import validate_excel_against_csv
from .config import Settings
from .paths import DataPaths, DataPathsError
from .profile_service import ProfileService
from .usage_profile import FluviusDataError
from .user_config import ConfigError, load_user_config
from .sources import SourceDiscoveryError, VnrSourceScraper

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
    # compare
    # ---------------------------------------------------------

    compare_parser = subparsers.add_parser(
        "compare",
        help="Vergelijk energieproducten voor een profiel.",
    )

    compare_parser.add_argument(
        "--data",
        type=Path,
        default=None,
        help=(
            "Expliciete map met genormaliseerde data. "
            "Zonder deze optie wordt de actieve dataset gebruikt."
        ),
    )

    compare_parser.add_argument(
        "--postcode",
        required=True,
        help="Belgische postcode, bijvoorbeeld 9280.",
    )

    compare_parser.add_argument(
        "--gemeente",
        default="",
        help=(
            "Gemeente. Aanbevolen wanneer een postcode "
            "meer dan één gemeente bevat."
        ),
    )

    compare_parser.add_argument(
        "--segment",
        default="Woning",
        choices=("Woning", "Onderneming"),
    )

    compare_parser.add_argument(
        "--year",
        type=int,
        default=datetime.now().year,
    )

    compare_parser.add_argument(
        "--month",
        type=int,
        choices=range(1, 13),
        metavar="{1..12}",
        default=datetime.now().month,
    )

    compare_parser.add_argument(
        "--dag",
        type=Decimal,
        default=D("2000"),
        help="Jaarlijkse dagafname in kWh.",
    )

    compare_parser.add_argument(
        "--nacht",
        type=Decimal,
        default=D("1500"),
        help="Jaarlijkse nachtafname in kWh.",
    )

    compare_parser.add_argument(
        "--piek",
        type=Decimal,
        default=D("4"),
        help="Geschatte gemiddelde maandpiek in kW.",
    )

    compare_parser.add_argument(
        "--meter",
        choices=("digitaal", "analoog"),
        default="digitaal",
    )

    compare_parser.add_argument(
        "--omvormer-kva",
        type=Decimal,
        default=D("0"),
        help="Omvormervermogen voor analoge prosumenten.",
    )

    compare_parser.add_argument(
        "--kwartier-csv",
        type=Path,
        default=None,
        help="Optioneel Fluviusbestand met kwartierwaarden.",
    )

    compare_parser.add_argument(
        "--entsoe-cache",
        type=Path,
        default=None,
        help="Optioneel pad naar de ENTSO-E-cache.",
    )

    compare_parser.add_argument(
        "--api-key",
        default=None,
        help=(
            "ENTSO-E API-key. Gebruik bij voorkeur de "
            "omgevingsvariabele ENTSOE_API_KEY."
        ),
    )

    compare_parser.add_argument(
        "--levies-eur-kwh",
        type=Decimal,
        default=D("0"),
        help=(
            "Federale of regionale heffingen buiten de "
            "DNB-tarieven, exclusief btw, in EUR/kWh."
        ),
    )

    compare_parser.add_argument(
        "--energy-fund-eur-year",
        type=Decimal,
        default=D("0"),
        help="Jaarlijkse bijdrage energiefonds in EUR.",
    )

    compare_parser.add_argument(
        "--top",
        type=positive_integer,
        default=20,
        help="Aantal resultaten dat wordt getoond.",
    )

    compare_parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Optioneel uitvoerpad voor alle resultaten.",
    )

    compare_parser.add_argument(
        "--validate-sources",
        action="store_true",
        help=(
            "Voer controles uit op de officiële Excelbronnen "
            "en de genormaliseerde CSV-bestanden."
        ),
    )

    compare_parser.set_defaults(handler=run_compare)

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
    ) as exc:
        logging.error("%s", exc)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
