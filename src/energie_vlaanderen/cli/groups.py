"""Bouwt de geneste commandostructuur (groep → actie) van de CLI.

Business-logica blijft in de domeinmodules (`ingest.py`, `audit.py`,
`db.py`, `paths_cmd.py`); dit bestand bepaalt enkel de *vorm* van de
commandolijn: welke groepen en acties er bestaan en welke handler elke
combinatie aanroept.

Registratievolgorde (bepaalt de volgorde in --help en het shell-menu):
    source, raw, staging, market, audit, version, db, paths
"""

from __future__ import annotations

import argparse
from datetime import datetime

from energie_vlaanderen.cli import audit, db, ingest, paths_cmd
from energie_vlaanderen.cli.args import add_json_flag, add_version_arg
from energie_vlaanderen.cli.helpers import positive_integer


def _add_source_group(subparsers: argparse._SubParsersAction) -> None:
    source_parser = subparsers.add_parser(
        "source",
        help="Officiële databronnen ontdekken en downloaden.",
    )
    actions = source_parser.add_subparsers(dest="action", required=True)

    download_parser = actions.add_parser(
        "download",
        help="Ontdek en download de officiële Excelbronnen naar een nieuwe raw-versie.",
    )
    download_parser.add_argument(
        "--year",
        type=int,
        default=datetime.now().year,
        help="Jaar van de distributienettarieven.",
    )
    add_json_flag(download_parser)
    download_parser.set_defaults(handler=ingest.run_download)

    list_parser = actions.add_parser(
        "list",
        help="Ontdek de actuele officiële Excelbronnen zonder ze te downloaden.",
    )
    list_parser.add_argument(
        "--year",
        type=int,
        default=datetime.now().year,
        help="Jaar van de distributienettarieven.",
    )
    add_json_flag(list_parser)
    list_parser.set_defaults(handler=ingest.run_sources)


def _add_raw_group(subparsers: argparse._SubParsersAction) -> None:
    raw_parser = subparsers.add_parser(
        "raw",
        help="Gedownloade bronversies beheren en controleren.",
    )
    actions = raw_parser.add_subparsers(dest="action", required=True)

    verify_parser = actions.add_parser(
        "verify",
        help="Controleer manifest, bestanden en checksums van een raw-versie.",
    )
    add_version_arg(verify_parser, help="Raw-versie-id die gecontroleerd wordt.")
    add_json_flag(verify_parser)
    verify_parser.set_defaults(handler=ingest.run_verify_raw)

    status_parser = actions.add_parser(
        "status",
        help="Toon de lokaal opgeslagen raw-versies en hun validatiestatus.",
    )
    add_json_flag(status_parser)
    status_parser.set_defaults(handler=ingest.run_raw_status)


def _add_staging_group(subparsers: argparse._SubParsersAction) -> None:
    staging_parser = subparsers.add_parser(
        "staging",
        help="Brondata verwerken naar gestagede datasets.",
    )
    actions = staging_parser.add_subparsers(dest="action", required=True)

    parse_parser = actions.add_parser(
        "parse",
        help="Verwerk een of meer ruwe werkboeken via de pipelines naar CSV in de staging map.",
    )
    add_version_arg(parse_parser, help="Raw-versie-id die verwerkt moet worden.")
    parse_parser.add_argument(
        "--only",
        choices=("vtest", "tariffs", "curves", "all"),
        default="all",
        help="Beperk de verwerking tot één dataset (standaard: all).",
    )
    parse_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overschrijf een bestaande tarieven-/curves-stagingmap (vtest wordt altijd overschreven).",
    )
    add_json_flag(parse_parser)
    parse_parser.set_defaults(handler=ingest.run_staging_parse)

    refine_parser = actions.add_parser(
        "refine",
        help="Scrape vtest.be voor contractmetadata (looptijd, datums, links, doelgroep).",
    )
    add_version_arg(refine_parser)
    refine_parser.add_argument("--postcode", default="9000")
    refine_parser.add_argument(
        "--segment",
        default="woning",
        choices=("woning", "onderneming"),
        help="Klantsegment ('Mijn woning' of 'Mijn onderneming'), standaard woning.",
    )
    refine_parser.add_argument(
        "--energy",
        default="elektriciteit",
        choices=("elektriciteit", "gas"),
        help="Energietype, standaard elektriciteit.",
    )
    refine_parser.add_argument(
        "--matrix",
        action="store_true",
        help=(
            "Draai alle segment x energie x DNB-combinaties (32 runs, 1 postcode "
            "per netbeheerder uit DnbPerGemeente.csv) i.p.v. één gerichte run. "
            "Negeert --postcode/--segment/--energy."
        ),
    )
    refine_parser.add_argument(
        "--no-download",
        action="store_true",
        help="Gebruik bestaande HTML-dump i.p.v. opnieuw te scrapen (vereist geen Selenium, niet beschikbaar bij --matrix).",
    )
    refine_parser.add_argument(
        "--browser",
        default="chrome",
        choices=("chrome", "firefox"),
        help="Browser voor Selenium (standaard: chrome).",
    )
    refine_parser.add_argument(
        "--show",
        action="store_true",
        help="Open browser zichtbaar (niet headless).",
    )
    refine_parser.add_argument(
        "--met-contractdetails",
        action="store_true",
        help=(
            "Haal per contract ook de tariefkaart- en voorwaardenlinks op. "
            "Die staan niet op de resultatenpagina maar in het detailpaneel, "
            "dat pas bij een klik geladen wordt — het kost dus een extra klik "
            "per uniek contract (~305 over de hele matrix)."
        ),
    )
    refine_parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Timeout in seconden voor wachten op vtest.be resultaten (standaard: 60s, voor traagge combinaties: 120-180s).",
    )
    add_json_flag(refine_parser)
    refine_parser.set_defaults(handler=ingest.run_refine_vtest)

    calibrate_parser = actions.add_parser(
        "calibrate",
        help=(
            "Reken de heffingen- en nettariefstructuur terug uit vtest.be door "
            "hetzelfde profiel bij verschillende verbruiken op te vragen."
        ),
    )
    add_version_arg(calibrate_parser)
    calibrate_parser.add_argument(
        "--postcode",
        default="9120",
        help=(
            "Postcode voor de kalibratie (standaard 9120). Heffingen zijn "
            "federaal en dus postcode-onafhankelijk; de nettarieven niet."
        ),
    )
    calibrate_parser.add_argument(
        "--segment",
        default="woning",
        choices=("woning", "onderneming"),
        help=(
            "Klantsegment (standaard woning). De accijnshervorming van 2023 "
            "gold enkel voor residentiële afnemers, dus beide segmenten "
            "dragen andere tarieven en krijgen een eigen rapport."
        ),
    )
    calibrate_parser.add_argument(
        "--browser",
        default="chrome",
        choices=("chrome", "firefox"),
        help="Browser voor Selenium (standaard: chrome).",
    )
    calibrate_parser.add_argument(
        "--show",
        action="store_true",
        help="Open browser zichtbaar (niet headless).",
    )
    add_json_flag(calibrate_parser)
    calibrate_parser.set_defaults(handler=ingest.run_staging_calibrate)


def _add_market_group(subparsers: argparse._SubParsersAction) -> None:
    market_parser = subparsers.add_parser(
        "market",
        help="Marktprijzen synchroniseren.",
    )
    actions = market_parser.add_subparsers(dest="action", required=True)

    sync_parser = actions.add_parser(
        "sync",
        help="Synchroniseer ENTSO-E marktprijzen voor een opgegeven periode naar de lokale cache.",
    )
    sync_parser.add_argument("--start", required=True, help="Startdatum (formaat: YYYY-MM-DD).")
    sync_parser.add_argument("--end", required=True, help="Einddatum (formaat: YYYY-MM-DD).")
    sync_parser.add_argument(
        "--no-api",
        action="store_true",
        help="Gebruik enkel de bestaande lokale cache (geen externe API-aanroepen).",
    )
    add_json_flag(sync_parser)
    sync_parser.set_defaults(handler=ingest.run_sync_market)


def _add_audit_group(subparsers: argparse._SubParsersAction) -> None:
    audit_parser = subparsers.add_parser(
        "audit",
        help="Dataversies controleren en goedkeuren.",
    )
    actions = audit_parser.add_subparsers(dest="action", required=True)

    status_parser = actions.add_parser("status", help="Bekijk de audit-status van een versie.")
    add_version_arg(status_parser)
    add_json_flag(status_parser)
    status_parser.set_defaults(handler=audit.run_audit_status)

    approve_parser = actions.add_parser("approve", help="Keur een specifieke versie goed.")
    add_version_arg(approve_parser)
    approve_parser.add_argument("--notes", default="", help="Optionele notities bij goedkeuring.")
    add_json_flag(approve_parser)
    approve_parser.set_defaults(handler=audit.run_audit_approve)

    golden_parser = actions.add_parser(
        "golden",
        help="Vergelijk gestagede CSVs cel voor cel met de bron-XLSX.",
    )
    add_version_arg(golden_parser)
    add_json_flag(golden_parser)
    golden_parser.set_defaults(handler=audit.run_audit_golden)

    set_golden_parser = actions.add_parser(
        "set-golden",
        help="Maak van een goedgekeurde versie de Golden Master.",
    )
    add_version_arg(set_golden_parser)
    add_json_flag(set_golden_parser)
    set_golden_parser.set_defaults(handler=audit.run_set_golden)

    sanity_parser = actions.add_parser(
        "sanity",
        help="Voer de volautomatische business logic checks uit op een versie.",
    )
    add_version_arg(sanity_parser)
    add_json_flag(sanity_parser)
    sanity_parser.set_defaults(handler=audit.run_audit_sanity)

    sample_parser = actions.add_parser(
        "sample",
        help="Neem een willekeurige steekproef uit de data voor visuele menselijke controle.",
    )
    add_version_arg(sample_parser)
    sample_parser.add_argument(
        "--count",
        type=positive_integer,
        default=3,
        help="Aantal rijen per dataset om te controleren (standaard: 3).",
    )
    add_json_flag(sample_parser)
    sample_parser.set_defaults(handler=audit.run_audit_sample)

    heffingen_parser = actions.add_parser(
        "heffingen",
        help=(
            "Controleer de heffingen-masterdata in config/heffingen/ op "
            "sluitende schijven, ontbrekende jaren en ongeverifieerde cijfers."
        ),
    )
    heffingen_parser.add_argument(
        "--datum",
        default=None,
        help=(
            "Peildatum (YYYY-MM-DD) voor de dekkingscontrole; "
            "standaard vandaag."
        ),
    )
    heffingen_parser.add_argument(
        "--streng",
        action="store_true",
        help="Behandel waarschuwingen als fouten (voor CI).",
    )
    add_json_flag(heffingen_parser)
    heffingen_parser.set_defaults(handler=audit.run_audit_heffingen)


def _add_version_group(subparsers: argparse._SubParsersAction) -> None:
    version_parser = subparsers.add_parser(
        "version",
        help="Dataversies publiceren en activeren.",
    )
    actions = version_parser.add_subparsers(dest="action", required=True)

    publish_parser = actions.add_parser(
        "publish",
        help=(
            "Publiceer een goedgekeurde versie: kopieer naar versions/, "
            "importeer naar de databank en activeer ze."
        ),
    )
    add_version_arg(publish_parser, help="Versie-id van de te publiceren staging-map.")
    publish_parser.add_argument(
        "--keep-staging",
        action="store_true",
        help="Bewaar de staging-map na publicatie (standaard: verwijderen).",
    )
    publish_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Publiceer ook als de versie niet goedgekeurd is "
            "(`audit approve` niet uitgevoerd)."
        ),
    )
    publish_parser.add_argument(
        "--skip-db",
        action="store_true",
        help=(
            "Sla de databankimport over. Let op: current.txt en de databank "
            "lopen dan uiteen."
        ),
    )
    publish_parser.add_argument(
        "--db-overwrite",
        action="store_true",
        help="Herlaad de versie in de databank als ze er al in zit.",
    )
    add_json_flag(publish_parser)
    publish_parser.set_defaults(handler=ingest.run_publish)


def _add_db_group(subparsers: argparse._SubParsersAction) -> None:
    db_parser = subparsers.add_parser(
        "db",
        help="Databankschema, import en status.",
    )
    actions = db_parser.add_subparsers(dest="action", required=True)

    init_parser = actions.add_parser(
        "init",
        help="Maak het databaseschema aan of upgrade het via Alembic-migraties.",
    )
    add_json_flag(init_parser)
    init_parser.set_defaults(handler=db.run_db_init)

    import_parser = actions.add_parser(
        "import",
        help="Importeer een gestagede versie (vtest, tarieven, ...) naar de databank.",
    )
    add_version_arg(import_parser, help="Versie-id om te importeren.")
    import_parser.add_argument(
        "--gemeente",
        action="store_true",
        help="Importeer ook DnbPerGemeente.csv (referentiedata — normaal éénmalig).",
    )
    import_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Verwijder bestaande rijen van deze versie en herlaad.",
    )
    add_json_flag(import_parser)
    import_parser.set_defaults(handler=db.run_db_import)

    verify_parser = actions.add_parser(
        "verify",
        help=(
            "Toets of de databank één op één overeenkomt met current.txt: "
            "zelfde actieve versie, aanwezig en geïmporteerd."
        ),
    )
    add_json_flag(verify_parser)
    verify_parser.set_defaults(handler=db.run_db_verify)

    status_parser = actions.add_parser(
        "status",
        help="Toon welke versies in de databank staan en hun importstatus.",
    )
    add_json_flag(status_parser)
    status_parser.set_defaults(handler=db.run_db_status)


def _add_paths_command(subparsers: argparse._SubParsersAction) -> None:
    paths_parser = subparsers.add_parser(
        "paths",
        help="Toon de gebruikte configuratie- en datamappen.",
    )
    paths_parser.set_defaults(handler=paths_cmd.run_paths)


def add_all(subparsers: argparse._SubParsersAction) -> None:
    """Registreer alle groepen en commando's, in de vaste menuvolgorde."""

    _add_source_group(subparsers)
    _add_raw_group(subparsers)
    _add_staging_group(subparsers)
    _add_market_group(subparsers)
    _add_audit_group(subparsers)
    _add_version_group(subparsers)
    _add_db_group(subparsers)
    _add_paths_command(subparsers)
