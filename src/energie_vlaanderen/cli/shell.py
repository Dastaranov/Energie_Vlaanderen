"""Interactieve shell: opstartscherm, prompt-lus, en het 'werking'-scherm.

Wordt gestart door `main()` in `cli/__init__.py` wanneer `energievergelijker`
zonder argumenten wordt aangeroepen. Niet-interactieve aanroepen
(`energievergelijker <groep> <actie> ...`) gaan hier nooit doorheen en
behouden hun bestaande, ongewijzigde tekst-/JSON-output.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import logging
import shlex

from energie_vlaanderen.cli.status import DashboardData, collect
from energie_vlaanderen.settings import Settings

LOG_NAME = "energievergelijker"

AFSLUITCOMMANDOS = {"exit", "quit", "q"}
HULPCOMMANDOS = {"help", "?"}

TAGLINE = "Beheer brongegevens, verwerkingspipelines en gepubliceerde datasets."

# (groep, actie) -> (ok-headline, warning-headline, fout-headline)
_HEADLINES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("source", "download"): ("Download voltooid", "Download voltooid met waarschuwingen", "Download mislukt"),
    ("source", "list"): ("Bronnen gevonden", "Bronnen gevonden met waarschuwingen", "Ontdekking mislukt"),
    ("raw", "verify"): ("Raw-versie is geldig", "Raw-versie is geldig, met waarschuwingen", "Raw-versie is ongeldig"),
    ("raw", "status"): ("Raw-versies opgehaald", "Raw-versies opgehaald met waarschuwingen", "Kan raw-status niet ophalen"),
    ("staging", "parse"): ("Verwerking voltooid", "Verwerking voltooid met waarschuwingen", "Verwerking mislukt"),
    ("staging", "refine"): ("Scrapen voltooid", "Scrapen voltooid met waarschuwingen", "Scrapen mislukt"),
    ("synergrid", "list"): ("Synergrid-bronnen gevonden", "Synergrid-bronnen gevonden met waarschuwingen", "Ontdekking mislukt"),
    ("synergrid", "download"): ("Download voltooid", "Download voltooid met waarschuwingen", "Download mislukt"),
    ("synergrid", "verify"): ("Synergrid raw-versie is geldig", "Synergrid raw-versie is geldig, met waarschuwingen", "Synergrid raw-versie is ongeldig"),
    ("synergrid", "status"): ("Synergrid raw-versies opgehaald", "Synergrid raw-versies opgehaald met waarschuwingen", "Kan Synergrid-status niet ophalen"),
    ("market", "sync"): ("Synchronisatie voltooid", "Synchronisatie voltooid met waarschuwingen", "Synchronisatie mislukt"),
    ("audit", "status"): ("Audit-status opgehaald", "Audit-status opgehaald met waarschuwingen", "Kan audit-status niet ophalen"),
    ("audit", "approve"): ("Versie goedgekeurd", "Versie goedgekeurd met waarschuwingen", "Goedkeuring mislukt"),
    ("audit", "golden"): ("Golden-audit geslaagd", "Golden-audit geslaagd met waarschuwingen", "Golden-audit gefaald"),
    ("audit", "set-golden"): ("Golden Master ingesteld", "Golden Master ingesteld met waarschuwingen", "Instellen Golden Master mislukt"),
    ("audit", "sanity"): ("Sanity check geslaagd", "Sanity check geslaagd met waarschuwingen", "Sanity check gefaald"),
    ("audit", "sample"): ("Steekproef gegenereerd", "Steekproef gegenereerd met waarschuwingen", "Steekproef mislukt"),
    ("version", "publish"): ("Publicatie geslaagd", "Publicatie geslaagd met waarschuwingen", "Publicatie mislukt"),
    ("db", "init"): ("Schema is up-to-date", "Schema is up-to-date, met waarschuwingen", "Schema-init mislukt"),
    ("db", "import"): ("Import geslaagd", "Import geslaagd met waarschuwingen", "Import mislukt"),
    ("db", "status"): ("Databankstatus opgehaald", "Databankstatus opgehaald met waarschuwingen", "Kan databankstatus niet ophalen"),
    ("paths", ""): ("Datapaden opgehaald", "Datapaden opgehaald met waarschuwingen", "Kan datapaden niet ophalen"),
}


def _pick_headline(group: str, action: str | None, rc: int, has_warnings: bool) -> tuple[str, str]:
    ok_text, warn_text, err_text = _HEADLINES.get(
        (group, action or ""),
        (f"{group} {action or ''} geslaagd".strip(), f"{group} {action or ''} voltooid met waarschuwingen".strip(), f"{group} {action or ''} mislukt".strip()),
    )
    if rc != 0:
        return "✗", err_text
    if has_warnings:
        return "!", warn_text
    return "✓", ok_text


def _clear_screen() -> None:
    """Wist het scherm via de ANSI-escape (werkt in de gangbare terminals)."""

    print("\033[2J\033[H", end="")


def _dispatch(args: argparse.Namespace, settings: Settings) -> tuple[int, str]:
    from energie_vlaanderen.cli import KNOWN_EXCEPTIONS

    buffer = io.StringIO()
    stream_handler = logging.StreamHandler(buffer)
    stream_handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger = logging.getLogger(LOG_NAME)
    logger.addHandler(stream_handler)
    # Onderdruk tijdelijk de root-handler van basicConfig (die anders meteen
    # naar het echte stderr schrijft) zodat log-regels enkel in de buffer
    # terechtkomen en dus chronologisch na de kopregel getoond worden.
    previous_propagate = logger.propagate
    logger.propagate = False

    try:
        with contextlib.redirect_stdout(buffer):
            rc = args.handler(args, settings)
    except KNOWN_EXCEPTIONS as exc:
        logger.error("%s", exc)
        rc = 2
    finally:
        logger.removeHandler(stream_handler)
        logger.propagate = previous_propagate

    text = buffer.getvalue()
    symbol, headline = _pick_headline(args.group, getattr(args, "action", None), rc, "WARNING" in text)

    rendered = f"{symbol} {headline}\n\n{text}"
    return rc, rendered


def _print_kv_block(rows: list[tuple[str, str]], width: int = 16) -> None:
    for label, value in rows:
        print(f"{label:<{width}}{value}")


def _print_header(data: DashboardData) -> None:
    titel = f"= Energie Vlaanderen - {data.datum} ="
    lijn = "=" * len(titel)
    print(lijn)
    print(titel)
    print(lijn)
    print(TAGLINE)


def _print_databank_block(data: DashboardData) -> None:
    print()
    _print_kv_block(
        [
            ("Databank:", data.databank),
            ("Server:", data.server),
            ("Verbinding:", data.verbinding),
            ("Laatste update:", data.laatste_update),
            ("Versie_data:", data.versie_data),
            ("Versie_users:", data.versie_users),
        ],
        width=20,
    )


def print_opstart_scherm(data: DashboardData) -> None:
    _print_header(data)
    print()
    print("Tarieven, contracten")
    print("-----------------------------------")
    _print_kv_block(
        [
            ("- Laatste run:", data.tarieven_laatste_run),
            ("- Links:", data.tarieven_links),
            ("- Paths:", data.tarieven_paths),
            ("- Tests:", data.tarieven_tests),
            ("- Audit:", data.tarieven_audit),
            ("- Versie:", data.tarieven_versie),
        ],
        width=16,
    )
    print()
    print("API - Entso-e / Andere")
    print("-----------------------------------")
    print(f"- API-keys: {data.api_keys}")
    print()
    print("Gebruikers")
    print("-----------------------------------")
    _print_kv_block(
        [
            ("- Aantal:", data.gebruikers_aantal),
            ("- Tests:", data.gebruikers_tests),
            ("- Audit:", data.gebruikers_audit),
            ("- Versie:", data.gebruikers_versie),
        ],
        width=16,
    )
    print()
    print("Simulaties")
    print("-----------------------------------")
    _print_kv_block(
        [
            ("- Tests:", data.simulaties_tests),
            ("- Audit:", data.simulaties_audit),
            ("- Versie:", data.simulaties_versie),
        ],
        width=16,
    )
    _print_databank_block(data)
    print()


def print_werking_scherm(data: DashboardData) -> None:
    _print_header(data)
    _print_databank_block(data)
    print()


def run_shell(parser: argparse.ArgumentParser, settings: Settings) -> int:
    data = collect(settings)
    _clear_screen()
    print_opstart_scherm(data)

    while True:
        try:
            line = input("Energie_vlaanderen >> ")
        except EOFError:
            print()
            break

        line = line.strip()
        if not line:
            continue
        if line in AFSLUITCOMMANDOS:
            break
        if line in HULPCOMMANDOS:
            _clear_screen()
            parser.print_help()
            input("\nDruk op Enter om verder te gaan ...")
            _clear_screen()
            print_werking_scherm(data)
            continue

        try:
            tokens = shlex.split(line)
        except ValueError as exc:
            print(f"✗ Ongeldige invoer: {exc}")
            continue

        try:
            args = parser.parse_args(tokens)
        except SystemExit:
            # argparse heeft zelf al een foutmelding of hulptekst getoond.
            continue

        _, rendered = _dispatch(args, settings)

        # Scherm wissen en opnieuw tekenen met het condensed dashboard erboven
        # en het resultaat van dit commando eronder — geeft telkens een frisse,
        # interactieve schermweergave i.p.v. eindeloos oplopende scrollback.
        data = collect(settings)
        _clear_screen()
        print_werking_scherm(data)
        print(rendered, end="")

    return 0
