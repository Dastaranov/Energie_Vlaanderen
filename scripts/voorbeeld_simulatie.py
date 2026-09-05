#!/usr/bin/env python3
"""
Voorbeeld van de simulatie-mini-API (`energie_vlaanderen.simulatie`).

Laat de drie basisbewerkingen zien: een lijst contracten opvragen, één
contract met al zijn metadata ophalen, en dat contract voor een gekozen
verbruiksprofiel doorrekenen.

Gebruik
-------
python scripts/voorbeeld_simulatie.py
python scripts/voorbeeld_simulatie.py --postcode 9120 --gemeente Haasdonk \
    --jaar 2026 --maand 8 --afname-dag 2000 --afname-nacht 1000
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal as D
from pathlib import Path

# ── project importeren via src/ pad, zoals de andere scripts/ ──────────────
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT / "src"))

from energie_vlaanderen.simulatie import open_simulatie, SimulatieProfiel  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postcode", default="9000")
    parser.add_argument("--gemeente", default="Gent")
    parser.add_argument("--segment", default="Woning")
    parser.add_argument("--meter", default="digitaal", choices=("digitaal", "analoog"))
    parser.add_argument("--jaar", type=int, default=2026)
    parser.add_argument("--maand", type=int, default=8)
    parser.add_argument("--afname-dag", type=D, default=D("2000"))
    parser.add_argument("--afname-nacht", type=D, default=D("1000"))
    args = parser.parse_args()

    # `tariefjaar` bepaalt welke nettarieven gelden; moet gelijk zijn aan
    # `--jaar` hierboven, anders weigert `bereken_contract()` (zie CLAUDE.md
    # "Het tariefjaar komt uit het werkboek, niet uit het versie-id").
    with open_simulatie(tariefjaar=args.jaar) as sim:

        # 1) Een lijst contracten, gefilterd op energievorm en segment.
        contracten = sim.lijst_contracten(energie_type="elektriciteit", segment=args.segment)
        print(f"{len(contracten)} elektriciteitscontracten in segment {args.segment!r}\n")
        for c in contracten[:5]:
            print(f"  {c.vreg_id:>8}  {c.leverancier:<20} {c.product_naam}")
        if len(contracten) > 5:
            print(f"  ... en nog {len(contracten) - 5}")
        print()

        # 2) Eén contract met alle metadata.
        gekozen = contracten[0]
        volledig = sim.haal_contract(gekozen.vreg_id)
        print(f"Contract {volledig.vreg_id} — {volledig.leverancier} {volledig.product_naam}")
        print(f"  tarief_type:      {volledig.tarief_type}")
        print(f"  looptijd:         {volledig.looptijd_tekst}")
        print(f"  groene stroom:    {volledig.groene_stroom} ({volledig.groene_stroom_type})")
        print(f"  tariefkaart:      {volledig.tariefkaart_url}")
        print()

        # 3) Dat contract doorrekenen voor een verbruiksprofiel.
        # `SimulatieProfiel` is een alias van `domain.models.Profile` en
        # verwacht jaarvolumes — zie de docstring van `bereken_kost()`.
        profiel = SimulatieProfiel(
            postcode=args.postcode,
            gemeente=args.gemeente,
            segment=args.segment,
            meter=args.meter,
            afname_dag_kwh=args.afname_dag,
            afname_nacht_kwh=args.afname_nacht,
        )
        kost = sim.bereken_contract(
            leverancier=volledig.leverancier,
            product_naam=volledig.product_naam,
            jaar=args.jaar,
            maand=args.maand,
            profiel=profiel,
        )
        print(f"Kost voor {profiel.afname_kwh} kWh/jaar op postcode {args.postcode}:")
        print(f"  leverancier:  {kost.supplier:>10.2f} EUR")
        print(f"  net:          {kost.grid:>10.2f} EUR")
        print(f"  heffingen:    {kost.levies:>10.2f} EUR")
        print(f"  btw:          {kost.vat:>10.2f} EUR")
        print(f"  totaal:       {kost.total:>10.2f} EUR")
        if kost.warnings:
            print("\nWaarschuwingen:")
            for w in kost.warnings:
                print(f"  - {w}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
