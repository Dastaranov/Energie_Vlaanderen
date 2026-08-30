"""Gedeelde helpers voor consistente CLI-output (tekst en --json)."""

from __future__ import annotations

import argparse
import json
from typing import Any, Callable


def print_kv(label: str, value: object, *, width: int = 15) -> None:
    """Print een uitgelijnde 'label : waarde'-regel, in de bestaande stijl."""

    print(f"{label:<{width}}: {value}")


def print_json(obj: Any) -> None:
    print(
        json.dumps(
            obj,
            ensure_ascii=False,
            indent=2,
        )
    )


def emit(
    args: argparse.Namespace,
    *,
    text_fn: Callable[[], None],
    json_obj: Any,
) -> None:
    """Print tekst of JSON, naargelang args.json (standaard False als niet ingesteld).

    Beslist niet over de exitcode — dat blijft de verantwoordelijkheid van de
    aanroepende handler, ook wanneer die code afhangt van de inhoud die hier
    geprint wordt (bv. verify-raw geeft in beide takken 0 of 2 terug).
    """

    if getattr(args, "json", False):
        print_json(json_obj)
    else:
        text_fn()
