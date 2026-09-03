#!/usr/bin/env python3
"""Reken de SPP-gewogen injectie-index na en leg hem naast wat VREG publiceert.

De meest gebruikte index op injectieproducten is
"M EPEX Spot Belgium/Belpex SPP_BE (kwartier)": het maandgemiddelde van de
Belgische spotprijs, **gewogen met het synthetische zonneproductieprofiel**. Dat
is niet het rekenkundig gemiddelde — de zon schijnt op de uren dat er veel zon
is, en dat zijn precies de goedkope uren. Op juni 2026 scheelt dat ruim 35%.

Wie injectie tegen de gemiddelde marktprijs waardeert, overschat de opbrengst
dus fors. Maar om het gewogen cijfer te mogen gebruiken moeten we eerst
aantonen dat we VREG's definitie juist hebben. Dit script toetst dat: het
berekent de index onder verschillende conventies en zet ze naast de
`index_value_A` uit de V-test-export.

    python scripts/check_injectie_index.py
    python scripts/check_injectie_index.py --versie <staging-of-versie-id>

Exitcode 0 = minstens één conventie valt binnen de tolerantie voor alle
vergelijkbare maanden, 1 = geen enkele conventie past, 2 = kon niet
controleren (bronbestanden ontbreken). Exitcode 1 is geen bug in dit script:
het betekent dat we de definitie nog niet kennen en dat een injectiebedrag op
deze index voorlopig `geschat` blijft.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from energie_vlaanderen.settings import Settings  # noqa: E402

# Hoeveel mag onze berekening van VREG's cijfer afwijken voordat we zeggen dat
# de conventie niet klopt? 1% is ruim: het laat afronding en een handvol
# ontbrekende kwartieren toe, maar niet een andere definitie.
TOLERANTIE = Decimal("0.01")

# Onder deze dekkingsgraad zeggen we niets over een maand: met de helft van de
# prijzen is elk gemiddelde een ander gemiddelde.
MINIMALE_DEKKING = 0.95


def _marktprijzen(cache: Path) -> pd.DataFrame:
    store = json.loads(cache.read_text(encoding="utf-8"))
    rijen = [r for k, v in store.items() if k.startswith("period:") and isinstance(v, list) for r in v]
    if not rijen:
        raise SystemExit(2)
    df = pd.DataFrame(rijen)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.drop_duplicates("timestamp").sort_values("timestamp")[["timestamp", "price_eur_mwh"]]


def _spp(profielen_dir: Path, jaar: int) -> pd.DataFrame:
    pad = profielen_dir / f"spp_{jaar}.csv"
    if not pad.is_file():
        raise FileNotFoundError(pad)
    df = pd.read_csv(pad, sep=";", encoding="utf-8-sig", usecols=["tijdstip", "waarde"])
    df["tijdstip"] = pd.to_datetime(df["tijdstip"], utc=True)
    return df.rename(columns={"tijdstip": "timestamp", "waarde": "spp"})


def _vreg_indexwaarden(vtest_dir: Path, jaar: int) -> dict[int, Decimal]:
    """De door VREG meegeleverde indexwaarde per maand, voor de SPP-kwartierindex."""
    pad = vtest_dir / "master_var_dyn.csv"
    if not pad.is_file():
        raise FileNotFoundError(pad)
    df = pd.read_csv(pad, sep=";", encoding="utf-8-sig", low_memory=False)
    sel = df[
        (df["direction"] == "Injectie")
        & (df["year"] == jaar)
        & (df["index_name_A"].astype(str).str.contains("SPP_BE (kwartier)", regex=False, na=False))
    ]
    uit: dict[int, Decimal] = {}
    for maand, groep in sel.groupby("month"):
        waarden = {
            Decimal(str(w).replace(",", ".")) for w in groep["index_value_A"].dropna().unique()
        }
        if len(waarden) == 1:
            uit[int(maand)] = waarden.pop()
    return uit


def _conventies(markt: pd.DataFrame, spp: pd.DataFrame) -> dict[str, dict[int, Decimal]]:
    """Bereken de index per maand onder een aantal kandidaat-definities."""
    samen = markt.merge(spp, on="timestamp", how="inner")
    samen["maand"] = samen["timestamp"].dt.month

    # Uurresolutie: eerst de kwartieren binnen een uur middelen, dan wegen.
    per_uur = samen.copy()
    per_uur["uur"] = per_uur["timestamp"].dt.floor("h")
    per_uur = per_uur.groupby("uur", as_index=False).agg(
        price_eur_mwh=("price_eur_mwh", "mean"), spp=("spp", "mean")
    )
    per_uur["maand"] = per_uur["uur"].dt.month

    def gewogen(df: pd.DataFrame) -> dict[int, Decimal]:
        uit = {}
        for maand, g in df.groupby("maand"):
            if g["spp"].sum() <= 0:
                continue
            uit[int(maand)] = Decimal(
                str((g["price_eur_mwh"] * g["spp"]).sum() / g["spp"].sum())
            )
        return uit

    def rekenkundig(df: pd.DataFrame) -> dict[int, Decimal]:
        return {
            int(maand): Decimal(str(g["price_eur_mwh"].mean()))
            for maand, g in df.groupby("maand")
        }

    conventies = {
        "SPP-gewogen, kwartier": gewogen(samen),
        "SPP-gewogen, uur": gewogen(per_uur),
        "rekenkundig, kwartier": rekenkundig(samen),
    }
    # Dezelfde reeksen, maar toegewezen aan de vólgende maand: een maandindex
    # wordt in de praktijk vaak op de daaropvolgende leveringsmaand toegepast.
    for naam in list(conventies):
        verschoven = {m + 1: v for m, v in conventies[naam].items() if m < 12}
        conventies[f"{naam}, maand +1"] = verschoven
    return conventies


def _dekking(markt: pd.DataFrame, spp: pd.DataFrame) -> dict[int, float]:
    """Welk deel van de SPP-punten per maand een marktprijs heeft."""
    samen = spp.merge(markt, on="timestamp", how="left")
    samen["maand"] = samen["timestamp"].dt.month
    return {
        int(maand): float(g["price_eur_mwh"].notna().mean())
        for maand, g in samen.groupby("maand")
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jaar", type=int, default=2026)
    parser.add_argument("--versie", help="Versie-id met vtest/ en profielen/. Standaard: zoeken.")
    args = parser.parse_args()

    settings = Settings.load(project_root=PROJECT_ROOT)
    data = settings.data_root

    try:
        markt = _marktprijzen(data / "market" / "entsoe_cache.json")
    except (FileNotFoundError, SystemExit):
        print("Geen marktprijscache gevonden. Draai eerst "
              "`energievergelijker market sync --start --end`.", file=sys.stderr)
        return 2

    kandidaten = []
    if args.versie:
        kandidaten = [data / "versions" / args.versie, data / "staging" / args.versie]
    else:
        # Nieuwste eerst: versie-id's beginnen met een tijdstempel, dus een
        # omgekeerde sortering geeft de recentste export. De oudste nemen zou
        # met verouderde indexwaarden vergelijken.
        kandidaten = sorted((data / "versions").glob("*"), reverse=True) + sorted(
            (data / "staging").glob("*"), reverse=True
        )

    profielen_dir = next((k / "profielen" for k in kandidaten if (k / "profielen" / f"spp_{args.jaar}.csv").is_file()), None)
    vtest_dir = next((k / "vtest" for k in kandidaten if (k / "vtest" / "master_var_dyn.csv").is_file()), None)
    if profielen_dir is None or vtest_dir is None:
        print(f"Geen SPP-profiel of V-test-export gevonden voor {args.jaar}.", file=sys.stderr)
        return 2

    spp = _spp(profielen_dir, args.jaar)
    vreg = _vreg_indexwaarden(vtest_dir, args.jaar)
    dekking = _dekking(markt, spp)
    conventies = _conventies(markt, spp)

    print(f"SPP-profiel : {profielen_dir}")
    print(f"V-test      : {vtest_dir}")
    print(f"Marktprijzen: {len(markt)} punten, {markt.timestamp.min().date()} .. {markt.timestamp.max().date()}")
    print()

    print(f"VREG-indexwaarden gevonden voor {len(vreg)} maand(en): "
          + (", ".join(str(m) for m in sorted(vreg)) or "geen"))
    print()

    bruikbaar = sorted(m for m in vreg if dekking.get(m, 0) >= MINIMALE_DEKKING)
    if not bruikbaar:
        print("Geen enkele maand heeft genoeg marktprijzen om te vergelijken "
              f"(drempel {MINIMALE_DEKKING:.0%}). Dekking per maand: "
              + ", ".join(f"{m}:{d:.0%}" for m, d in sorted(dekking.items())))
        return 2

    kop = "maand  dekking  VREG      " + "  ".join(f"{n[:22]:>22}" for n in conventies)
    print(kop)
    print("-" * len(kop))
    treffers: dict[str, list[bool]] = {n: [] for n in conventies}
    for maand in bruikbaar:
        regel = f"{maand:>5}  {dekking[maand]:>6.0%}  {vreg[maand]:>8}  "
        for naam, waarden in conventies.items():
            eigen = waarden.get(maand)
            if eigen is None:
                regel += f"{'-':>22}  "
                treffers[naam].append(False)
                continue
            afwijking = abs(eigen - vreg[maand]) / vreg[maand] if vreg[maand] else Decimal("1")
            past = afwijking <= TOLERANTIE
            treffers[naam].append(past)
            regel += f"{float(eigen):>13.4f} {float(afwijking):>7.1%}  "
        print(regel)

    print()
    geslaagd = [naam for naam, uitslagen in treffers.items() if uitslagen and all(uitslagen)]
    if geslaagd:
        print("Conventie gevonden: " + ", ".join(geslaagd))
        print(f"Alle {len(bruikbaar)} vergelijkbare maanden vallen binnen {TOLERANTIE:.0%}.")
        return 0

    beste = max(treffers, key=lambda n: sum(treffers[n]))
    print("Geen enkele conventie reproduceert de gepubliceerde indexwaarde.")
    print(f"Beste kandidaat: '{beste}' ({sum(treffers[beste])}/{len(bruikbaar)} maanden binnen {TOLERANTIE:.0%}).")
    print()
    print("Zolang dit zo is, mag een injectiebedrag op deze index alleen met de")
    print("door VREG meegeleverde indexwaarde gerekend worden — nooit met een")
    print("zelf berekende — en draagt het resultaat exactheidsklasse 'geschat'.")
    print("Nog niet uitgesloten: ex-post in plaats van ex-ante SPP, een ander")
    print("perimeter dan SPP_BE, en de betekenis van de TH/HI/LO-varianten.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
