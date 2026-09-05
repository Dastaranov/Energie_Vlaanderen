#!/usr/bin/env python3
"""
Voorbeeld van de scenario-API (`energie_vlaanderen.scenario`).

Laat de kernbewerkingen zien: een dossier doorrekenen (de basislijn), een
"wat als ik een ander contract had"-scenario, een batterijscenario, en de
opslag van het resultaat als JSON — de bouwstenen achter "vergelijken van
contracten" en "wat als ik batterijen/zonnepanelen/een EV/een warmtepomp
bijplaats".

Vereist een databank met geïmporteerde tarieven (zie CLAUDE.md, sectie "Data
versioning") en een `gebruiker.toml` in de projectroot (zie
`gebruiker.voorbeeld.toml`).

Gebruik
-------
python scripts/voorbeeld_scenario.py
python scripts/voorbeeld_scenario.py --toml gebruiker.toml \\
    --van 2026-01-01 --tot 2027-01-01
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal as D
from pathlib import Path

# ── project importeren via src/ pad, zoals de andere scripts/ ──────────────
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT / "src"))

from energie_vlaanderen.gebruikers.models import Contracttype, EnergieType  # noqa: E402
from energie_vlaanderen.scenario import (  # noqa: E402
    AnderContractScenario,
    BatterijScenario,
    open_scenario,
)
from energie_vlaanderen.scenario import opslag  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toml", default=str(_ROOT / "gebruiker.toml"))
    parser.add_argument("--van", type=date.fromisoformat, default=date(2026, 1, 1))
    parser.add_argument("--tot", type=date.fromisoformat, default=date(2027, 1, 1))
    parser.add_argument("--uitvoer", default=str(_ROOT / "data" / "simulaties"))
    args = parser.parse_args()

    with open_scenario(args.toml) as ctx:
        if ctx.dossier.punt(EnergieType.ELEKTRICITEIT) is None:
            print("Dit dossier heeft geen elektriciteitsaansluiting; niets te tonen.")
            return 1

        # 1) De basislijn: het dossier zoals het vandaag staat.
        basislijn = ctx.bereken(args.van, args.tot)
        print(f"Basislijn {args.van}..{args.tot}: {basislijn.totalen.get('totaal', 'n.v.t.')} EUR\n")

        # 2) "Wat als ik in het verleden een ander contract had genomen?"
        ander_contract = AnderContractScenario(
            energie_type=EnergieType.ELEKTRICITEIT,
            leverancier="Bolt", product="Bolt Variabel",
            contracttype=Contracttype.VARIABEL,
        )
        resultaat_contract = ander_contract.voer_uit(
            ctx.dossier, conn=ctx.conn, settings=ctx.settings,
            van=args.van, tot=args.tot, basislijn=basislijn,
        )
        print(f"{resultaat_contract.naam}")
        print(f"  basislijn: {resultaat_contract.totaal_basislijn:.2f} EUR")
        print(f"  scenario:  {resultaat_contract.totaal_scenario:.2f} EUR")
        print(f"  verschil:  {resultaat_contract.verschil_eur['totaal']:.2f} EUR\n")

        pad_contract = opslag.sla_op(
            resultaat_contract, Path(args.uitvoer) / "ander_contract.json",
        )
        print(f"  opgeslagen als {pad_contract}\n")

        # 3) "Wat als ik batterijen bijplaats?" — vereist masterdata voor het
        # gekozen merk/model in config/hardware/batterijen/.
        try:
            batterij = BatterijScenario(
                merk="Marstek", model="Venus E", jaarverbruik_kwh=D("3500"),
            )
            resultaat_batterij = batterij.voer_uit(
                ctx.dossier, conn=ctx.conn, settings=ctx.settings,
                van=args.van, tot=args.tot, basislijn=basislijn,
            )
            print(f"{resultaat_batterij.naam}")
            print(f"  verschil: {resultaat_batterij.verschil_eur['totaal']:.2f} EUR")
            for waarschuwing in resultaat_batterij.warnings:
                print(f"  ! {waarschuwing}")
            opslag.sla_op(resultaat_batterij, Path(args.uitvoer) / "batterij.yaml", formaat="yaml")
        except Exception as exc:  # noqa: BLE001 - dit is een demoscript
            print(f"Batterijscenario overgeslagen: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
