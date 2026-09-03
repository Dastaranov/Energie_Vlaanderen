#!/usr/bin/env python3
"""Leg `config/heffingen/bijdrage_energiefonds.toml` naast vlaanderen.be.

De bijdrage energiefonds is de enige heffing in deze masterdata waarvoor een
publieke, jaarlijks bijgewerkte tabel bestaat. Tot nu toe werd die met de hand
vergeleken — het soort controle dat precies één keer per jaar nodig is en
daarom vergeten wordt. `docs/jaarwissel 2026-2027.md` waarschuwt bovendien dat
het energiefonds bij een ontbrekend jaar *hard faalt*: een berekening over 2027
stopt zodra dat jaar niet aangevuld is.

    # Tegen de live pagina (netwerk nodig)
    python scripts/check_energiefonds.py

    # Tegen een opgeslagen kopie (geen netwerk)
    python scripts/check_energiefonds.py --html tests/fixturen/heffingen/vlaanderen_energiefonds_2026.html

Exitcode 0 = alles komt overeen, 1 = afwijking of ontbrekend jaar, 2 = kon niet
controleren. Exitcode 1 is geen bug in dit script: het betekent dat de Vlaamse
overheid de tarieven gewijzigd of aangevuld heeft en dat de masterdata bij moet.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from energie_vlaanderen.heffingen.repository import (  # noqa: E402
    HeffingenError,
    HeffingenRepository,
)
from energie_vlaanderen.ingest.heffingen.energiefonds import (  # noqa: E402
    EnergiefondsError,
    EnergiefondsScraper,
    lees_bestand,
)
from energie_vlaanderen.settings import Settings  # noqa: E402


def _masterdata() -> dict[tuple[int, str, str], object]:
    repo = HeffingenRepository.load(PROJECT_ROOT / "config" / "heffingen")
    return {
        (t.jaar, t.spanningsniveau, t.klantcategorie): t.eur_per_maand
        for t in repo.energiefonds_tarieven()
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--html",
        help="Opgeslagen kopie van de pagina in plaats van de live site.",
    )
    args = parser.parse_args()

    try:
        if args.html:
            gepubliceerd = lees_bestand(Path(args.html))
            bron = args.html
        else:
            settings = Settings.load(project_root=PROJECT_ROOT)
            scraper = EnergiefondsScraper(settings)
            gepubliceerd = scraper.tarieven()
            bron = scraper.url
    except EnergiefondsError as exc:
        print(f"Kon de tarieftabel niet lezen: {exc}", file=sys.stderr)
        return 2

    try:
        eigen = _masterdata()
    except (HeffingenError, OSError) as exc:
        print(f"Kon de masterdata niet lezen: {exc}", file=sys.stderr)
        return 2

    print(f"Bron       : {bron}")
    print(f"Gepubliceerd: {len(gepubliceerd)} tarieven")
    print(f"Masterdata  : {len(eigen)} tarieven")
    print()

    afwijkingen: list[str] = []
    ontbreekt_in_masterdata: list[str] = []

    for rij in sorted(gepubliceerd, key=lambda r: r.sleutel):
        etiket = f"{rij.jaar} {rij.spanningsniveau}/{rij.klantcategorie or '-'}"
        onze = eigen.get(rij.sleutel)
        if onze is None:
            ontbreekt_in_masterdata.append(f"{etiket} = {rij.eur_per_maand}")
        elif onze != rij.eur_per_maand:
            afwijkingen.append(
                f"{etiket}: masterdata {onze}, gepubliceerd {rij.eur_per_maand}"
            )

    gepubliceerde_sleutels = {r.sleutel for r in gepubliceerd}
    verdwenen = [
        f"{j} {s}/{k or '-'} = {v}"
        for (j, s, k), v in sorted(eigen.items())
        if (j, s, k) not in gepubliceerde_sleutels
    ]

    for titel, regels in (
        ("AFWIJKINGEN", afwijkingen),
        ("NIEUW OP DE PAGINA, NOG NIET IN DE MASTERDATA", ontbreekt_in_masterdata),
        ("WEL IN DE MASTERDATA, NIET MEER OP DE PAGINA", verdwenen),
    ):
        if regels:
            print(f"{titel}:")
            for regel in regels:
                print(f"  - {regel}")
            print()

    # Het lopende en het volgende jaar horen erin te staan: het energiefonds
    # faalt hard op een ontbrekend jaar, dus een berekening over januari kan in
    # december al stukvallen.
    jaren = {r.jaar for r in gepubliceerd}
    volgend = date.today().year + 1
    if volgend not in jaren:
        print(
            f"LET OP: {volgend} staat nog niet op de pagina. Het energiefonds "
            "faalt hard op een ontbrekend jaar, dus een berekening over "
            f"{volgend} stopt tot de Vlaamse overheid publiceert."
        )
        print()

    if afwijkingen or ontbreekt_in_masterdata or verdwenen:
        print("Masterdata en pagina lopen uiteen.")
        return 1

    print("Masterdata en pagina komen op alle punten overeen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
