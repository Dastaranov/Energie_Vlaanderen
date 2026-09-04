#!/usr/bin/env python3
"""Haal de tariefkaarten van de lopende contracten op en bewaar ze.

Een variabel contract bevriest bij ondertekening zijn formule; de V-test-export
levert alleen de kaart die vandaag verkocht wordt. Het verschil is meetbaar
(11,74 EUR/jaar aan vaste vergoeding op een echte Eneco-afrekening) en niet met
code te overbruggen. Anders dan de index, die uit de day-ahead historiek altijd
nog terug te rekenen valt, is een tariefkaart weg zodra de leverancier hem
vervangt — vandaag archiveren is de enige manier om een contract van vandaag
over drie jaar nog exact na te rekenen.

    python scripts/archiveer_tariefkaarten.py            # alles
    python scripts/archiveer_tariefkaarten.py --leverancier ENGIE
    python scripts/archiveer_tariefkaarten.py --droogloop # toon wat er zou gebeuren
    python scripts/archiveer_tariefkaarten.py --json

Het archief staat in `data/tariefkaarten/` en valt buiten git: het zijn
PDF's van derden, tientallen MB, en het is afgeleide data.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from energie_vlaanderen.infrastructure.db.connection import get_engine  # noqa: E402
from energie_vlaanderen.ingest.tariefkaarten import (  # noqa: E402
    TariefkaartArchief,
    bronnen_uit_databank,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--leverancier", help="Alleen deze leverancier (deelstring).")
    parser.add_argument("--map", default="data/tariefkaarten",
                        help="Doelmap (standaard data/tariefkaarten).")
    parser.add_argument("--pauze", type=float, default=0.5,
                        help="Seconden tussen twee verzoeken (standaard 0,5).")
    parser.add_argument("--droogloop", action="store_true",
                        help="Toon wat er opgehaald zou worden, haal niets op.")
    parser.add_argument("--json", action="store_true", dest="als_json")
    args = parser.parse_args(argv)

    with get_engine(ROOT).connect() as conn:
        bronnen = bronnen_uit_databank(conn)

    if args.leverancier:
        naald = args.leverancier.casefold()
        bronnen = [b for b in bronnen if naald in b.leverancier.casefold()]

    if not bronnen:
        print("Geen tariefkaart-URL's gevonden.", file=sys.stderr)
        return 2

    if args.droogloop:
        per_leverancier: dict[str, int] = {}
        for b in bronnen:
            per_leverancier[b.leverancier] = per_leverancier.get(b.leverancier, 0) + 1
        if args.als_json:
            print(json.dumps({"aantal": len(bronnen), "per_leverancier": per_leverancier},
                             indent=2, ensure_ascii=False))
        else:
            print(f"{len(bronnen)} tariefkaarten van {len(per_leverancier)} leveranciers:")
            for naam, aantal in sorted(per_leverancier.items(), key=lambda x: -x[1]):
                print(f"  {aantal:4d}  {naam}")
        return 0

    archief = TariefkaartArchief(ROOT / args.map, pauze=args.pauze)

    def voortgang(nummer, totaal, bron):
        if not args.als_json:
            print(f"\r[{nummer:3d}/{totaal}] {bron.leverancier[:24]:24s} "
                  f"{bron.product[:28]:28s}", end="", flush=True)

    rapport = archief.archiveer(bronnen, voortgang=voortgang)
    if not args.als_json:
        print("\r" + " " * 70 + "\r", end="")

    if args.als_json:
        print(json.dumps(rapport.as_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"Archief    : {archief.wortel}")
        print(f"Nieuw      : {rapport.nieuw}")
        print(f"Ongewijzigd: {rapport.ongewijzigd}")
        print(f"Gewijzigd  : {rapport.gewijzigd}")
        print(f"Mislukt    : {rapport.mislukt}")
        if rapport.fouten:
            print("\nMislukte kaarten (per leverancier uit te zoeken):")
            for f in rapport.fouten:
                print(f"  {f['leverancier']} — {f['product']}: {f['reden'][:100]}")

    # Mislukkingen zijn geen fout van dit script: een leverancier die zijn kaart
    # achter een aanmeldpagina zet is een bevinding, geen crash. Exitcode 1
    # alleen wanneer er niets gelukt is.
    if rapport.nieuw + rapport.ongewijzigd + rapport.gewijzigd == 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
