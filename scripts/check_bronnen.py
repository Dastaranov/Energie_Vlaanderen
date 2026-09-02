#!/usr/bin/env python3
"""Kijk of VREG nieuwe bronbestanden gepubliceerd heeft.

Vergelijkt wat er nu op de VREG-pagina's staat met `config/bronregister.toml`,
het register van wat de pipeline effectief verwerkt heeft. Een verschil
betekent dat er nieuwe data klaarstaat, niet dat er iets stuk is.

    python scripts/check_bronnen.py              # rapporteren
    python scripts/check_bronnen.py --json       # voor CI
    python scripts/check_bronnen.py --bijwerken  # register gelijkzetten

Exitcodes: 0 = niets nieuws, 3 = nieuwe bron gevonden, 2 = kon niet
controleren (pagina onbereikbaar, register onleesbaar). 3 is bewust geen 1:
"er is nieuwe data" is een signaal, geen fout, en een workflow hoort daar iets
anders mee te doen dan met een crash.

Draaien na een vondst:

    energievergelijker source download --year <jaar>
    energievergelijker staging parse --version <nieuwe versie>
    python scripts/check_bronnen.py --bijwerken
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from energie_vlaanderen.ingest.sources import (  # noqa: E402
    SourceDiscoveryError,
    VnrSourceScraper,
)
from energie_vlaanderen.ingest.synergrid_sources import SynergridSourceScraper  # noqa: E402
from energie_vlaanderen.settings import Settings  # noqa: E402

REGISTER = PROJECT_ROOT / "config" / "bronregister.toml"


def _register_laden() -> dict:
    try:
        with REGISTER.open("rb") as fh:
            return tomllib.load(fh)
    except OSError as exc:
        raise SystemExit(f"Bronregister niet leesbaar: {exc}")


def _register_schrijven(bronnen: dict[str, str], versie: str | None) -> None:
    """Herschrijf enkel de bestandsnamen; commentaar en opmerkingen blijven.

    Bewust regel-voor-regel in plaats van met een TOML-writer: het register
    bestaat vooral uit uitleg, en die is meer waard dan de elegantie van een
    her-serialisatie die alle commentaar zou weggooien.
    """
    regels = REGISTER.read_text(encoding="utf-8").splitlines(keepends=True)
    uit: list[str] = []
    huidige_kind: str | None = None
    for regel in regels:
        gestript = regel.strip()
        if gestript.startswith("kind = "):
            huidige_kind = gestript.split("=", 1)[1].strip().strip('"')
        elif gestript.startswith("bestandsnaam = ") and huidige_kind in bronnen:
            inspringing = regel[: len(regel) - len(regel.lstrip())]
            regel = f'{inspringing}bestandsnaam = "{bronnen[huidige_kind]}"\n'
        elif gestript.startswith("bijgewerkt_op = "):
            regel = f'bijgewerkt_op = "{date.today().isoformat()}"\n'
        elif gestript.startswith("verwerkte_versie = ") and versie:
            regel = f'verwerkte_versie = "{versie}"\n'
        uit.append(regel)
    REGISTER.write_text("".join(uit), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Geef JSON i.p.v. tekst.")
    parser.add_argument(
        "--bijwerken",
        action="store_true",
        help="Zet het register gelijk aan wat er nu online staat.",
    )
    parser.add_argument(
        "--versie",
        help="Versie-id om als verwerkte_versie te noteren bij --bijwerken.",
    )
    parser.add_argument(
        "--jaar",
        type=int,
        default=date.today().year,
        help="Jaar voor de tariefbestanden (standaard: dit jaar).",
    )
    args = parser.parse_args()

    register = _register_laden()
    verwacht = {b["kind"]: b["bestandsnaam"] for b in register["bron"]}

    settings = Settings.load()
    gevonden_artefacten: dict[str, object] = {}
    try:
        gevonden_artefacten.update(VnrSourceScraper(settings).discover(args.jaar))
    except (SourceDiscoveryError, OSError) as exc:
        boodschap = f"Kon de VREG-pagina's niet raadplegen: {exc}"
        if args.json:
            print(json.dumps({"status": "onbereikbaar", "fout": str(exc)}, ensure_ascii=False))
        else:
            print(boodschap)
        return 2

    try:
        gevonden_artefacten.update(SynergridSourceScraper(settings).discover(args.jaar))
    except (SourceDiscoveryError, OSError) as exc:
        boodschap = f"Kon de Synergrid-pagina niet raadplegen: {exc}"
        if args.json:
            print(json.dumps({"status": "onbereikbaar", "fout": str(exc)}, ensure_ascii=False))
        else:
            print(boodschap)
        return 2

    gevonden = {kind: art.filename for kind, art in gevonden_artefacten.items()}

    nieuw: list[dict[str, str]] = []
    ongewijzigd: list[str] = []
    ontbrekend: list[str] = []
    for kind, verwachte_naam in sorted(verwacht.items()):
        actuele_naam = gevonden.get(kind)
        if actuele_naam is None:
            ontbrekend.append(kind)
        elif actuele_naam != verwachte_naam:
            nieuw.append(
                {
                    "kind": kind,
                    "verwerkt": verwachte_naam,
                    "online": actuele_naam,
                    "url": gevonden_artefacten[kind].url,
                }
            )
        else:
            ongewijzigd.append(kind)

    if args.bijwerken:
        _register_schrijven(gevonden, args.versie)

    if args.json:
        print(
            json.dumps(
                {
                    "status": "nieuw" if nieuw else "actueel",
                    "jaar": args.jaar,
                    "nieuw": nieuw,
                    "ongewijzigd": ongewijzigd,
                    "ontbrekend": ontbrekend,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(f"Register  : {REGISTER}")
        print(f"Verwerkt  : versie {register.get('verwerkte_versie', '?')}")
        print()
        for kind in ongewijzigd:
            print(f"[ONGEWIJZIGD] {kind}: {verwacht[kind]}")
        for item in nieuw:
            print(f"[NIEUW]       {item['kind']}")
            print(f"              verwerkt: {item['verwerkt']}")
            print(f"              online  : {item['online']}")
        for kind in ontbrekend:
            print(
                f"[ONTBREEKT]   {kind}: staat in het register maar is niet "
                "op de pagina gevonden."
            )
        print()
        if nieuw:
            print(
                f"{len(nieuw)} nieuwe bron(nen). Draai "
                f"`energievergelijker source download --year {args.jaar}`, "
                "verwerk de versie en zet daarna het register gelijk met "
                "`--bijwerken --versie <id>`."
            )
        elif ontbrekend:
            print("Geen nieuwe bronnen, maar wel ontbrekende — pagina-indeling gewijzigd?")
        else:
            print("Alles staat gelijk met wat de pipeline verwerkt heeft.")

    if ontbrekend:
        return 2
    return 3 if nieuw else 0


if __name__ == "__main__":
    raise SystemExit(main())
