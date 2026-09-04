#!/usr/bin/env python3
"""Lees de gearchiveerde tariefkaarten uit en leg ze naast de databank.

Wat een kaart draagt en de V-test-export niet, is de **bevroren** formule van
een lopend contract. Dit script haalt die eruit — coëfficiënt, index, constante,
eenheid, btw-vlag — en toetst ze meteen tegen `tarief_afname` voor de maand van
de kaart. Die toets is de validatie: waar de coëfficiënt overeenkomt, is de
lezing bevestigd; waar ze verschilt, is er iets te onderzoeken. Dat oordeel
hoort niet in een regex.

    python scripts/parse_tariefkaarten.py               # samenvatting + toets
    python scripts/parse_tariefkaarten.py --leverancier Eneco
    python scripts/parse_tariefkaarten.py --schrijf     # data/tariefkaarten/formules.json
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from energie_vlaanderen.infrastructure.db.connection import get_engine  # noqa: E402
from energie_vlaanderen.ingest.tariefkaart_parser import (  # noqa: E402
    lees_pdf,
    parse_kaart,
)
from energie_vlaanderen.ingest.tariefkaarten import TariefkaartArchief  # noqa: E402


def _uit_databank(conn, kaartmaand: str) -> dict:
    """(leverancier, product, energie) -> verzameling param_a's van die maand."""
    import sqlalchemy as sa

    if not kaartmaand:
        return {}
    rijen = conn.execute(sa.text("""
        select l.naam, p.product_naam, p.energie_type,
               t.param_a, t.vaste_vergoeding_jaar
        from tarief_afname t
        join energie_product p on p.id = t.product_id
        join leverancier l on l.id = p.leverancier_id
        where t.geldig_van = :maand and t.param_a is not null
    """), {"maand": f"{kaartmaand}-01"}).all()
    uit: dict = {}
    for naam, product, energie, a, vast in rijen:
        sleutel = (naam.casefold(), product.casefold(), energie)
        gegevens = uit.setdefault(sleutel, {"a": set(), "vast": set()})
        gegevens["a"].add(Decimal(str(a)))
        if vast is not None:
            gegevens["vast"].add(Decimal(str(vast)))
    return uit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--leverancier")
    parser.add_argument("--map", default="data/tariefkaarten")
    parser.add_argument("--schrijf", action="store_true")
    args = parser.parse_args(argv)

    archief = TariefkaartArchief(ROOT / args.map)
    kaarten = archief.lees_register().get("kaarten", [])
    if args.leverancier:
        naald = args.leverancier.casefold()
        kaarten = [k for k in kaarten if naald in k["leverancier"].casefold()]
    if not kaarten:
        print("Geen kaarten in het archief.", file=sys.stderr)
        return 2

    ontleed, per_maand = [], {}
    for kaart in kaarten:
        pad = archief.wortel / kaart["bestand"]
        if not pad.is_file():
            continue
        try:
            inhoud = parse_kaart(lees_pdf(pad))
        except Exception as exc:  # noqa: BLE001
            ontleed.append({**_kern(kaart), "fout": str(exc)[:120]})
            continue
        ontleed.append({**_kern(kaart), **inhoud.as_dict()})
        per_maand.setdefault(inhoud.kaartmaand, 0)
        per_maand[inhoud.kaartmaand] += 1

    met_formule = [o for o in ontleed if o.get("formules")]
    met_maand = [o for o in ontleed if o.get("kaartmaand")]
    print(f"kaarten          : {len(ontleed)}")
    print(f"met een formule  : {len(met_formule)}")
    print(f"met een kaartmaand: {len(met_maand)}  {sorted(per_maand)[-3:]}")

    # -- de toets ---------------------------------------------------------
    # Draagt de kaart geen leesbare maand, dan geldt de meest recente maand in
    # de export: het archief haalt de kaart op die vandaag verkocht wordt, en
    # dat is dezelfde kaart die VREG in zijn laatste snapshot beschrijft. Waar
    # de kaart de maand wél noemt, wint die.
    with get_engine(ROOT).connect() as conn:
        import sqlalchemy as sa
        laatste = conn.execute(
            sa.text("select max(geldig_van) from tarief_afname")
        ).scalar()
        laatste_maand = laatste.strftime("%Y-%m") if laatste else ""
        maanden = {o.get("kaartmaand") or laatste_maand for o in met_formule}
        tabellen = {m: _uit_databank(conn, m) for m in maanden if m}
    print(f"terugval-maand    : {laatste_maand} (laatste snapshot in de export)")

    bevestigd = afwijkend = ongetoetst = vast = 0
    eenheden: dict[str, int] = {}
    afwijkingen = []
    for o in met_formule:
        db = tabellen.get(o.get("kaartmaand") or laatste_maand, {})
        gegevens = db.get(
            (o["leverancier"].casefold(), o["product"].casefold(), o["energie_type"])
        )
        if not gegevens:
            ongetoetst += 1
            continue
        if gegevens["a"] == {Decimal(0)}:
            # Een vast product draagt geen indexcoëfficiënt. De formule op zo'n
            # kaart hoort bij de optionele dynamische afrekening en niet bij de
            # contractprijs; ertegen toetsen zou een afwijking melden die geen
            # afwijking is.
            vast += 1
            continue
        kaart_a = {Decimal(f["a"]) for f in o["formules"]}
        # De eenheid van de kaart is niet altijd afgedrukt, maar wél af te
        # leiden: een coëfficiënt in €/MWh is precies tien keer die in
        # ct/kWh, en de databank draagt de laatste. Een factor die klopt is
        # dus bewijs voor de eenheid, geen aanname erover — en wat op geen
        # enkele factor uitkomt, blijft een afwijking.
        gevonden = None
        for factor, eenheid in ((Decimal(1), "ct/kWh"),
                                (Decimal("0.1"), "EUR/MWh"),
                                (Decimal(100), "EUR/kWh")):
            omgerekend = {a * factor for a in kaart_a}
            if omgerekend & gegevens["a"]:
                gevonden = eenheid
                break
            # Een kaart drukt vaak minder decimalen af dan de export draagt:
            # Luminus zet 0,0923 waar de databank 0,092320 heeft. Dat is een
            # afronding op de kaart en geen ander tarief. Er wordt daarom ook
            # op het aantal decimalen van de kaart vergeleken — en niet met een
            # tolerantie, want die zou ook een écht verschil doorlaten.
            for kaartwaarde in omgerekend:
                cijfers = -kaartwaarde.as_tuple().exponent
                if any(round(dbwaarde, cijfers) == kaartwaarde
                       for dbwaarde in gegevens["a"]):
                    gevonden = f"{eenheid} (kaart afgerond)"
                    break
            if gevonden:
                break
        if gevonden:
            bevestigd += 1
            eenheden[gevonden] = eenheden.get(gevonden, 0) + 1
        else:
            afwijkend += 1
            afwijkingen.append(
                f"{o['leverancier'][:22]:22s} {o['product'][:22]:22s} "
                f"kaart {sorted(kaart_a)[:3]} vs databank {sorted(gegevens['a'])[:3]}"
            )
    print(f"\ncoëfficiënt bevestigd door de databank : {bevestigd}")
    for eenheid, aantal in sorted(eenheden.items(), key=lambda x: -x[1]):
        print(f"    waarvan de kaart rekent in {eenheid:8s}: {aantal}")
    print(f"coëfficiënt wijkt af                   : {afwijkend}")
    print(f"niet te toetsen (product/maand ontbreekt): {ongetoetst}")
    print(f"vast product, geen indexcoëfficiënt      : {vast}")
    for regel in afwijkingen[:12]:
        print("   ", regel)

    if args.schrijf:
        doel = archief.wortel / "formules.json"
        doel.write_text(json.dumps(ontleed, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        print(f"\ngeschreven: {doel}")
    return 0


def _kern(kaart: dict) -> dict:
    return {
        "vreg_id": kaart["vreg_id"], "leverancier": kaart["leverancier"],
        "product": kaart["product"], "energie_type": kaart["energie_type"],
        "sha256": kaart["sha256"], "bestand": kaart["bestand"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
