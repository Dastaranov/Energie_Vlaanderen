#!/usr/bin/env python3
"""Leg `config/heffingen/` naast een kalibratierapport van vtest.be.

De masterdata in `config/heffingen/` is handgeschreven; het kalibratierapport
is teruggerekend uit vtest.be zelf. Dit script zegt of ze hetzelfde beweren.

    # Tegen een bestaand rapport (geen netwerk, geen browser)
    python scripts/check_tarieven.py --rapport data/staging/<versie>/calibration_report.json

    # Rapport eerst zelf ophalen (Selenium + Chrome/Firefox nodig, ~13 min)
    python scripts/check_tarieven.py --versie <versie> --scrape

Exitcode 0 = alles komt overeen, 1 = afwijking gevonden, 2 = kon niet
controleren (rapport ontbreekt, component niet in het rapport, ...). Een
afwijking is geen bug in dit script: het betekent dat de wetgever iets
gewijzigd heeft en dat `config/heffingen/` bijgewerkt moet worden.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from energie_vlaanderen.heffingen.repository import (  # noqa: E402
    HeffingenError,
    HeffingenRepository,
)

# vtest.be rondt op eurocent af en de teruggerekende helling erft die ruis.
# Over de gebruikte meetspannen blijft dat ruim onder een halve cent per MWh.
TOLERANTIE_EUR_MWH = Decimal("0.01")

# Welke component in het kalibratierapport hoort bij welke energievorm en
# klantcategorie in de masterdata. vtest.be benoemt dezelfde heffing niet
# overal gelijk — "Bijzondere accijns" bij de woning-elektriciteitspagina,
# "Bijzondere accijns (per kWh)" bij gas en bij ondernemingen — dus we
# proberen beide labels.
ACCIJNS_LABELS = (
    "Heffingen|Bijzondere accijns",
    "Heffingen|Bijzondere accijns (per kWh)",
)

# De klantcategorie in de masterdata hangt af van het gekalibreerde segment.
# Ze door elkaar halen is de snelste manier om een fout te introduceren: de
# hervorming van 2023 gold enkel voor residentiële afnemers, waardoor woning
# en onderneming wezenlijk andere tarieven dragen.
CATEGORIE_PER_SEGMENT = {
    "woning": "niet_zakelijk",
    "onderneming": "zakelijk_laagspanning",
}

# De energievorm heet in de masterdata "aardgas", in de kalibratie "gas".
ENERGIEVORM_IN_CONFIG = {"elektriciteit": "elektriciteit", "gas": "aardgas"}

# Het vervoerstarief van Fluxys staat in geen VREG-werkboek en wordt als
# masterdata bijgehouden; vtest.be rapporteert het wel, dus het is op dezelfde
# manier te toetsen als de heffingen.
TRANSPORT_LABEL = "Nettarieven|Afnametarief transport (per kWh)"

# Het vervoerstarief is klein (1,56 EUR/MWh), dus de tolerantie van
# 0,01 EUR/MWh die voor de accijnzen ruim genoeg is, dekt hier 0,6% van de
# waarde af — genoeg om een echt verschil te verbergen. Voor transport toetsen
# we daarom relatief: 0,05% van het tarief, ruim boven de afrondingsruis maar
# ruim onder een systematisch verschil.
TRANSPORT_TOLERANTIE_RELATIEF = Decimal("0.0005")

# vtest.be rekent voor gewone woningproducten met 1,5565 in plaats van 1,56
# EUR/MWh — consistent 0,2244% lager over vijf verbruikspunten. De oorzaak is
# niet vastgesteld (zie config/nettarieven/transport_aardgas.toml). Het staat
# hier vastgepind in plaats van weggemoffeld onder een ruime tolerantie: zolang
# de afwijking precies deze grootte heeft, is ze bekend; verandert ze, dan
# hoort dat op te vallen.
BEKENDE_AFWIJKING = {
    "niet_zakelijk": {
        "relatief": Decimal("0.002244"),
        "marge": Decimal("0.0002"),
        "uitleg": (
            "vtest.be past op woningproducten 1,5565 EUR/MWh toe in plaats van "
            "het officiële 1,56; oorzaak niet vastgesteld"
        ),
    },
}


def _d(waarde: object) -> Decimal:
    return Decimal(str(waarde))


def _rapport_laden(pad: Path) -> dict:
    try:
        return json.loads(pad.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"Kalibratierapport niet leesbaar: {exc}")


def _gemeten_bedragen(rapport: dict, energy: str) -> list[tuple[int, Decimal]]:
    """De ruwe accijnsbedragen, als (kWh, EUR excl. btw).

    We toetsen tegen de metingen zelf en niet tegen de teruggerekende
    schijven: de metingen zijn wat vtest.be werkelijk zei, de schijven zijn
    daar al een interpretatie van.
    """
    blok = rapport.get(energy)
    if not blok:
        raise SystemExit(f"Rapport bevat geen blok voor '{energy}'.")

    punten: list[tuple[int, Decimal]] = []
    for meting in blok["metingen"]:
        label = next((l for l in ACCIJNS_LABELS if l in meting["componenten"]), None)
        if label is None:
            continue
        aandeel = _d(meting.get("dominant_aandeel", {}).get(label, "0"))
        if aandeel < Decimal("0.6"):
            # Leveranciersafhankelijk in deze meting; geen zuivere heffing.
            continue
        punten.append((int(meting["kwh"]), _d(meting["componenten"][label])))
    return sorted(punten)


def _controleer_transport(
    rapport: dict, categorie: str, peildatum: date
) -> tuple[int, int]:
    """Leg config/nettarieven/ naast de gemeten vervoerstarieven.

    Geeft (gecontroleerd, afwijkingen) terug.
    """
    from energie_vlaanderen.nettarieven.transport import (  # noqa: PLC0415
        TransportTariefError,
        TransportTariefRepository,
    )

    blok = rapport.get("gas")
    if not blok:
        return 0, 0

    punten = [
        (int(m["kwh"]), _d(m["componenten"][TRANSPORT_LABEL]))
        for m in blok["metingen"]
        if TRANSPORT_LABEL in m["componenten"]
        and _d(m.get("dominant_aandeel", {}).get(TRANSPORT_LABEL, "0")) >= Decimal("0.6")
    ]
    if not punten:
        return 0, 0

    try:
        repo = TransportTariefRepository.load(PROJECT_ROOT / "config" / "nettarieven")
    except TransportTariefError as exc:
        print(f"\n[OVERGESLAGEN] vervoerstarief: {exc}")
        return 0, 0

    print(f"\nvervoerstarief aardgas / {categorie} — {len(punten)} meetpunten")
    gecontroleerd = afwijkingen = 0
    for kwh, gemeten in sorted(punten):
        try:
            berekend = repo.kost_per_jaar("aardgas", categorie, _d(kwh), peildatum)
        except TransportTariefError as exc:
            print(f"  {kwh:>7} kWh  KAN NIET BEREKENEN: {exc}")
            afwijkingen += 1
            continue

        gecontroleerd += 1
        verschil = berekend - gemeten
        relatief = abs(verschil) / berekend if berekend else Decimal(0)

        bekend = BEKENDE_AFWIJKING.get(categorie)
        # De marge moet de afronding op eurocent meenemen: op een bedrag van
        # 6,24 EUR is één cent al 0,16%, ruim meer dan de systematische
        # afwijking van 0,2244% zelf. Een vaste relatieve marge zou het
        # kleinste meetpunt daardoor onterecht als nieuw verschil melden.
        marge = (
            bekend["marge"] + Decimal("0.005") / berekend if bekend and berekend else None
        )
        if bekend and abs(relatief - bekend["relatief"]) <= marge:
            merk = "BEKEND"
        elif relatief <= TRANSPORT_TOLERANTIE_RELATIEF:
            merk = "OK"
        else:
            merk = "AFWIJKING"
            afwijkingen += 1

        print(
            f"  {kwh:>7} kWh  vtest {gemeten:>10} EUR   config "
            f"{berekend.quantize(Decimal('0.01')):>10} EUR   "
            f"verschil {verschil.quantize(Decimal('0.01')):>8} EUR "
            f"({(relatief * 100).quantize(Decimal('0.0001'))}%)  {merk}"
        )

    if BEKENDE_AFWIJKING.get(categorie):
        print(f"  BEKEND = {BEKENDE_AFWIJKING[categorie]['uitleg']}")

    return gecontroleerd, afwijkingen


def controleer(rapport: dict, config_dir: Path, peildatum: date) -> int:
    repo = HeffingenRepository.load(config_dir)
    # Oudere rapporten (schema 1) kennen enkel woning.
    segment = rapport.get("segment", "woning")
    categorie = CATEGORIE_PER_SEGMENT.get(segment)
    if categorie is None:
        raise SystemExit(f"Onbekend segment in het rapport: {segment!r}.")
    print(f"Segment   : {segment} -> klantcategorie {categorie}")

    afwijkingen = 0
    gecontroleerd = 0

    for energy in ("elektriciteit", "gas"):
        if energy not in rapport:
            continue
        energievorm = ENERGIEVORM_IN_CONFIG[energy]
        punten = _gemeten_bedragen(rapport, energy)
        if not punten:
            print(
                f"[OVERGESLAGEN] {energievorm}/{categorie}: geen bruikbare "
                "accijnsmetingen in het rapport."
            )
            continue

        print(f"\n{energievorm} / {categorie} — {len(punten)} meetpunten")
        for kwh, gemeten in punten:
            try:
                berekend, _ = repo.bereken_accijns_en_energiebijdrage(
                    energievorm, categorie, _d(kwh), peildatum
                )
            except HeffingenError as exc:
                print(f"  {kwh:>7} kWh  KAN NIET BEREKENEN: {exc}")
                afwijkingen += 1
                continue

            gecontroleerd += 1
            verschil = berekend - gemeten
            # Vergelijk in EUR/MWh, zodat de tolerantie niet met het verbruik
            # meegroeit en een groot verbruik niet stilzwijgend meer mag afwijken.
            per_mwh = abs(verschil) * Decimal(1000) / _d(kwh)
            merk = "OK" if per_mwh <= TOLERANTIE_EUR_MWH else "AFWIJKING"
            if per_mwh > TOLERANTIE_EUR_MWH:
                afwijkingen += 1
            print(
                f"  {kwh:>7} kWh  vtest {gemeten:>10} EUR   config "
                f"{berekend.quantize(Decimal('0.01')):>10} EUR   "
                f"verschil {verschil.quantize(Decimal('0.01')):>8} EUR "
                f"({per_mwh.quantize(Decimal('0.0001'))} EUR/MWh)  {merk}"
            )

    transport_gecontroleerd, transport_afwijkingen = _controleer_transport(
        rapport, categorie, peildatum
    )
    gecontroleerd += transport_gecontroleerd
    afwijkingen += transport_afwijkingen

    print()
    if not gecontroleerd:
        print("Niets kunnen controleren — rapport en masterdata sluiten niet aan.")
        return 2
    if afwijkingen:
        print(
            f"{afwijkingen} afwijking(en) op {gecontroleerd} meetpunten. "
            "Werk config/heffingen/ bij aan de hand van het kalibratierapport."
        )
        return 1
    print(f"Alle {gecontroleerd} meetpunten komen overeen met config/heffingen/.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rapport",
        type=Path,
        help="Pad naar een bestaand calibration_report.json.",
    )
    parser.add_argument(
        "--versie",
        help="Versie-id; het rapport wordt dan in data/staging/<versie>/ gezocht.",
    )
    parser.add_argument(
        "--scrape",
        action="store_true",
        help="Haal een vers rapport op bij vtest.be (vereist --versie en Selenium).",
    )
    parser.add_argument(
        "--postcode",
        default="9120",
        help="Postcode voor een verse kalibratie (standaard 9120).",
    )
    parser.add_argument(
        "--segment",
        default="woning",
        choices=("woning", "onderneming"),
        help=(
            "Welk segmentrapport gecontroleerd wordt; bepaalt ook welk "
            "rapportbestand bij --versie gezocht wordt."
        ),
    )
    parser.add_argument(
        "--datum",
        default=None,
        help="Peildatum YYYY-MM-DD voor de masterdata; standaard vandaag.",
    )
    args = parser.parse_args()

    peildatum = date.fromisoformat(args.datum) if args.datum else date.today()
    config_dir = PROJECT_ROOT / "config" / "heffingen"

    if args.scrape:
        if not args.versie:
            parser.error("--scrape vereist --versie.")
        from energie_vlaanderen.ingest.vtest.calibration import VTestCalibrator
        from energie_vlaanderen.settings import Settings

        settings = Settings.load()
        staging = settings.data_root / "staging" / args.versie
        rapport_pad = VTestCalibrator().run(
            staging_dir=staging, postcode=args.postcode, segment=args.segment
        )
    elif args.rapport:
        rapport_pad = args.rapport
    elif args.versie:
        from energie_vlaanderen.settings import Settings

        settings = Settings.load()
        achtervoegsel = "" if args.segment == "woning" else f"_{args.segment}"
        rapport_pad = (
            settings.data_root
            / "staging"
            / args.versie
            / f"calibration_report{achtervoegsel}.json"
        )
    else:
        parser.error("Geef --rapport, --versie of --versie met --scrape.")

    print(f"Rapport   : {rapport_pad}")
    print(f"Masterdata: {config_dir}")
    print(f"Peildatum : {peildatum.isoformat()}")
    return controleer(_rapport_laden(Path(rapport_pad)), config_dir, peildatum)


if __name__ == "__main__":
    raise SystemExit(main())
