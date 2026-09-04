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
    parser.add_argument(
        "--kandidaten", action="store_true",
        help=("Toon per leverancier wat er nog niet eenduidig te herleiden is, "
              "uit het bestaande register. Haalt niets op — de overwogen links "
              "zijn bij de vorige run al bewaard."),
    )
    args = parser.parse_args(argv)

    if args.kandidaten:
        return _toon_kandidaten(ROOT / args.map, args.leverancier, args.als_json)

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


def _toon_kandidaten(wortel: Path, leverancier: str | None, als_json: bool) -> int:
    """Wat er nog open staat, uit het register en zonder netwerk.

    De resolver bewaart bij elke mislukking de links die hij overwogen heeft.
    Het uitzoekwerk per leverancier is daarmee een opzoeking: je ziet in één
    oogopslag of de kaart er wél staat maar onder een naam die de generieke
    match niet herkent, of dat er helemaal niets te halen valt.
    """
    from energie_vlaanderen.ingest.tariefkaarten import TariefkaartArchief

    register = TariefkaartArchief(wortel).lees_register()
    fouten = register.get("fouten", [])
    if leverancier:
        naald = leverancier.casefold()
        fouten = [f for f in fouten if naald in f["leverancier"].casefold()]
    if als_json:
        print(json.dumps(fouten, indent=2, ensure_ascii=False))
        return 0

    per_leverancier: dict[str, list] = {}
    for f in fouten:
        per_leverancier.setdefault(f["leverancier"], []).append(f)

    for naam, groep in sorted(per_leverancier.items(), key=lambda x: -len(x[1])):
        zonder = [f for f in groep if not f.get("kandidaten")]
        print(f"\n{'=' * 72}\n{naam}  —  {len(groep)} open"
              + (f", {len(zonder)} zonder kandidaten" if zonder else ""))
        if zonder:
            print(f"  onbereikbaar: {zonder[0]['reden'][:90]}")
        # De kandidaatlijst is per landingspagina gelijk; één keer tonen
        # volstaat om de regel af te lezen.
        getoond = set()
        for f in groep:
            if not f.get("kandidaten"):
                continue
            sleutel = tuple(sorted(k["label"] for k in f["kandidaten"]))
            producten = [g["product"] for g in groep
                         if tuple(sorted(k["label"] for k in g.get("kandidaten", []))) == sleutel]
            if sleutel in getoond:
                continue
            getoond.add(sleutel)
            print(f"  producten : {', '.join(sorted(set(producten)))[:150]}")
            print(f"  pagina    : {f['url'][:100]}")
            for k in f["kandidaten"][:8]:
                print(f"     {k['label'][:44]:44s}  {k['url'][-60:]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
