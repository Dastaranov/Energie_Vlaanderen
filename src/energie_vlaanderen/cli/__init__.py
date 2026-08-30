"""EnergieVergelijker command-line interface.

Publieke API (blijft stabiel voor tests/test_cli.py, het `energievergelijker`
console-script en `python -m energie_vlaanderen.cli`):
    build_parser, main, run_paths, run_publish
    (en alle overige run_*-handlers, zie __all__).

Exitcode-conventie, gebruikt door alle commando's:
    0 = succes
    2 = validatie-/business-foutmelding of een verwachte operationele fout
        (ongeldige versie, ontbrekende stagingmap, pipeline die weigert,
        gefaalde sanity check, ontbrekende optionele dependency, ...)
    Ongevangen excepties buiten de tuple hieronder in main() vallen door
    naar Python's standaard traceback + exitcode 1 — dat zijn bugs, geen
    verwachte gebruikersfouten.
"""

from __future__ import annotations

import argparse
import logging
import sys

from energie_vlaanderen.data.paths import DataPathsError
from energie_vlaanderen.data.repository import DataRepositoryError
from energie_vlaanderen.ingest.downloader import DownloadError
from energie_vlaanderen.ingest.raw_store import RawStoreError
from energie_vlaanderen.ingest.sources import SourceDiscoveryError
from energie_vlaanderen.settings import Settings

from energie_vlaanderen.cli import groups
from energie_vlaanderen.cli.audit import (
    run_audit_approve,
    run_audit_golden,
    run_audit_sample,
    run_audit_sanity,
    run_audit_status,
    run_set_golden,
)
from energie_vlaanderen.cli.db import run_db_import, run_db_init, run_db_status
from energie_vlaanderen.cli.ingest import (
    run_download,
    run_parse_curves,
    run_parse_tariffs,
    run_parse_vtest,
    run_publish,
    run_raw_status,
    run_refine_vtest,
    run_sources,
    run_staging_parse,
    run_sync_market,
    run_verify_raw,
)
from energie_vlaanderen.cli.paths_cmd import run_paths, show_paths

LOG = logging.getLogger("energievergelijker")

__all__ = [
    "build_parser",
    "main",
    "run_paths",
    "show_paths",
    "run_sources",
    "run_download",
    "run_verify_raw",
    "run_raw_status",
    "run_parse_vtest",
    "run_parse_tariffs",
    "run_parse_curves",
    "run_staging_parse",
    "run_refine_vtest",
    "run_sync_market",
    "run_publish",
    "run_audit_status",
    "run_audit_approve",
    "run_set_golden",
    "run_audit_golden",
    "run_audit_sanity",
    "run_audit_sample",
    "run_db_init",
    "run_db_import",
    "run_db_status",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="energievergelijker",
        description="EnergieVergelijker voor Vlaanderen",
    )

    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default="INFO",
        help="Niveau van logberichten.",
    )

    subparsers = parser.add_subparsers(
        dest="group",
        required=True,
        title="commando's",
    )

    # Volgorde: source, raw, staging, market, audit, version, db, paths.
    groups.add_all(subparsers)

    return parser


# Excepties die zowel main() als de interactieve shell op dezelfde manier
# afvangen: een verwachte, gebruikersgerichte fout (exitcode 2), geen bug.
KNOWN_EXCEPTIONS = (
    DataPathsError,
    DataRepositoryError,
    FileNotFoundError,
    SourceDiscoveryError,
    ValueError,
    DownloadError,
    RawStoreError,
)


def main(argv: list[str] | None = None) -> int:
    raw_argv = sys.argv[1:] if argv is None else argv

    if not raw_argv:
        from energie_vlaanderen.cli import shell

        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        return shell.run_shell(build_parser(), Settings.load())

    parser = build_parser()
    args = parser.parse_args(raw_argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s %(message)s",
    )

    try:
        settings = Settings.load()
        return args.handler(args, settings)
    except KNOWN_EXCEPTIONS as exc:
        logging.error("%s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
