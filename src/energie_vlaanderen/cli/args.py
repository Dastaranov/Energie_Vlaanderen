from __future__ import annotations

import argparse


def add_version_arg(
    parser: argparse.ArgumentParser,
    *,
    help: str = "Versie-id die verwerkt moet worden.",
) -> None:
    """Registreer de veelgebruikte --version optie met een per-commando hulptekst."""

    parser.add_argument(
        "--version",
        required=True,
        help=help,
    )


def add_json_flag(parser: argparse.ArgumentParser) -> None:
    """Registreer de --json optie voor machineleesbare output."""

    parser.add_argument(
        "--json",
        action="store_true",
        help="Geef het resultaat als JSON weer.",
    )
