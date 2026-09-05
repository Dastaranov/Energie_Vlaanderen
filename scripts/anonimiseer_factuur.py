#!/usr/bin/env python3
"""Anonimiseer een energiefactuur (PDF of tekst) tot een deelbare kopie.

`data/referentie/LEESMIJ.md` legt uit waarom dit nodig is: een factuur draagt
naam, adres, EAN en klantnummer, en die horen niet in git of in een
gedeelde kopie thuis — alleen de *cijfers* (periode, verbruik, tarieven,
kostenopbouw) zijn de referentiecase. Tot nu toe gebeurde dat overtypen met de
hand naar `tests/fixturen/facturen/*.toml`. Dit script maakt in plaats daarvan
een geanonimiseerde platte-tekstversie van het hele document, voor wie de
volledige lay-out wil delen (bv. om een nieuw doel te laten uitzoeken) zonder
de persoonsgegevens.

Bewust **onafhankelijk**: geen import uit `src/energie_vlaanderen/` nodig, dus
dit werkt ook op een kale checkout of los gekopieerd. De PDF-extractie
hergebruikt wel het patroon uit `ingest/tariefkaart_parser.py::lees_pdf()`
(`pdftotext -layout` i.p.v. de leesvolgorde, anders vallen kolommen als de
kostenopbouw-tabel uiteen).

Werkwijze — twee lagen:

1. **Automatisch, op patroon**: EAN-codes, IBAN's, e-mailadressen,
   telefoonnummers, en het label + de waarde bij "Klantnummer",
   "Factuurnummer", "Referentie", "Contractnummer", "Dossiernummer" en
   "Login". Dit werkt zonder verdere invoer en dekt wat op elke factuur
   dezelfde vorm heeft.
2. **Op maat**: naam en adres staan nergens op een vaste plek met een vast
   label — ze staan bovenaan als brief, herhaald in een adresblok, en soms
   nog eens in een contractoverzicht. Daarom moet je ze meegeven
   (`--naam`, `--straat`, `--postcode`, `--gemeente`, of los met `--extra`):
   elke waarde wordt woord-voor-woord en geheel gezocht en vervangen, ongeacht
   hoofdlettergebruik.

Zonder `--naam`/`--straat`/`--gemeente`/`--extra` waarschuwt het script: de
automatische regels alleen laten een naam en adres gewoon staan.

    python scripts/anonimiseer_factuur.py factuur.pdf \\
        --naam "Mevr. Marleen De Beck" --straat "Tramstraat 40" \\
        --postcode 9220 --gemeente Moerzeke \\
        --klantnummer "2 201 908 475" -o factuur-anoniem.txt

Verwerkt ook meerdere bestanden in één aanroep (bv. een factuur + haar
detailbijlage) met dezelfde vervangingen.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

PLACEHOLDER_NAAM = "[NAAM]"
PLACEHOLDER_ADRES = "[ADRES]"
PLACEHOLDER_EAN = "[EAN]"
PLACEHOLDER_IBAN = "[REKENINGNUMMER]"
PLACEHOLDER_EMAIL = "[E-MAILADRES]"
PLACEHOLDER_TEL = "[TELEFOONNUMMER]"

# Labels waarvan de *waarde* (niet het label zelf) een klantidentificatie is.
GELABELDE_VELDEN = [
    "Klantnummer",
    "Factuurnummer",
    "Referentie",
    "Contractnummer",
    "Dossiernummer",
    "Polisnummer",
    "Login",
]


def lees_pdf(pad: Path) -> str:
    """De tekstlaag van een PDF, via pdftotext -layout.

    Zelfde keuze als `ingest/tariefkaart_parser.py::lees_pdf()`: `-layout` en
    niet de leesvolgorde, anders valt een tabel als de kostenopbouw uiteen
    over losse regels die niets meer met elkaar te maken lijken te hebben.
    """
    uitslag = subprocess.run(  # noqa: S603 - vaste argumenten, geen shell
        ["pdftotext", "-layout", str(pad), "-"],
        capture_output=True, text=True,
    )
    if uitslag.returncode != 0:
        raise RuntimeError(f"pdftotext mislukte op {pad}: {uitslag.stderr[:200]}")
    return uitslag.stdout


def _vervang_gelabeld_veld(tekst: str, label: str) -> str:
    """Vervangt de waarde na een label als "Klantnummer: 2 201 908 475".

    De waarde is alles t/m het einde van de regel na het label en een
    scheidingsteken (":" of "-"), of tot een dubbele spatie — een factuur in
    kolommen (`pdftotext -layout`) zet vaak nog een volgend veld verderop op
    dezelfde regel, en dat mag niet mee weg.
    """
    patroon = re.compile(
        rf"(\b{re.escape(label)}\s*[:\-]?\s*)([^\n]+?)(?=\s{{2,}}|$)",
        re.IGNORECASE | re.MULTILINE,
    )

    def _vervanger(match: re.Match[str]) -> str:
        return f"{match.group(1)}[{label.upper()}]"

    return patroon.sub(_vervanger, tekst)


def anonimiseer(
    tekst: str,
    *,
    extra_termen: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Anonimiseert `tekst` en geeft (resultaat, waarschuwingen) terug."""
    waarschuwingen: list[str] = []

    for label in GELABELDE_VELDEN:
        tekst = _vervang_gelabeld_veld(tekst, label)

    # "Betreffende je Afrekening <nummer>" — het factuurnummer, in een zin en
    # dus niet via GELABELDE_VELDEN te vangen: "Afrekening" is ook een gewoon
    # Nederlands woord ("jaarafrekening", "deze afrekening") en zou als label
    # veel te veel platte tekst opeten.
    tekst = re.sub(
        r"(Betreffende je Afrekening\s+)[\d ]+(?=\s*-)",
        r"\1[AFREKENINGNUMMER]",
        tekst,
    )

    # EAN: 18 cijfers, steeds voorafgegaan door het label "EAN" op deze
    # facturen (elektriciteit én aardgas hebben er elk één).
    tekst = re.sub(r"(EAN\s*)\d{15,18}", rf"\1{PLACEHOLDER_EAN}", tekst)

    # IBAN: land + controlegetal + BBAN, met of zonder spaties om de vier
    # tekens (zoals "BE46 0003 2544 8336").
    tekst = re.sub(
        r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}\b", PLACEHOLDER_IBAN, tekst,
    )

    # E-mailadres en telefoonnummer (Belgische notaties: 0499 12 34 56,
    # +32 499 12 34 56, 09/123.45.67, ...).
    tekst = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", PLACEHOLDER_EMAIL, tekst)
    tekst = re.sub(
        r"(?:\+32\s?|0)\d{1,3}[/ .]?\d{2,3}[ .]?\d{2}[ .]?\d{2}\b",
        PLACEHOLDER_TEL,
        tekst,
    )

    # Vaste aanspreekvorm + naam: "Dhr.", "Mevr.", "De heer", "Mevrouw",
    # gevolgd door de naam tot het einde van de regel of een dubbele spatie
    # (dezelfde kolomgrens als bij de gelabelde velden hierboven).
    tekst = re.sub(
        r"((?:Dhr|Mevr)\.?|De heer|Mevrouw)\s+[A-Za-zÀ-ÿ'’.\- ]+?(?=\s{2,}|$|\n)",
        rf"\1 {PLACEHOLDER_NAAM}",
        tekst,
        flags=re.MULTILINE,
    )

    # Adresvelden met een label: "Verbruiksadres", "Leveringsadres",
    # "Factuuradres", "Leveringspunt", gevolgd door ":" of "-" en het adres
    # op dezelfde regel (kan doorlopen met een tweede regel straat+postcode).
    tekst = re.sub(
        r"((?:Verbruiks|Leverings|Factuur)adres|Leveringspunt)"
        r"(\s*[:\-]\s*)([^\n]+)",
        rf"\1\2{PLACEHOLDER_ADRES}",
        tekst,
        flags=re.IGNORECASE,
    )

    if extra_termen:
        for term in extra_termen:
            term = term.strip()
            if not term:
                continue
            tekst = re.sub(re.escape(term), PLACEHOLDER_NAAM, tekst, flags=re.IGNORECASE)
    else:
        waarschuwingen.append(
            "Geen --naam/--straat/--gemeente/--extra meegegeven: een naam of "
            "adres dat zonder label of aanspreekvorm in de tekst staat "
            "(bv. herhaald in een adresblok of contractoverzicht) blijft dan "
            "onaangeroerd. Controleer de uitvoer met het oog voor je ze deelt."
        )

    return tekst, waarschuwingen


def _verwerk_bestand(
    pad: Path, uitvoer: Path, extra_termen: list[str],
) -> list[str]:
    if pad.suffix.lower() == ".pdf":
        ruwe_tekst = lees_pdf(pad)
    else:
        ruwe_tekst = pad.read_text(encoding="utf-8", errors="replace")

    resultaat, waarschuwingen = anonimiseer(ruwe_tekst, extra_termen=extra_termen)
    uitvoer.write_text(resultaat, encoding="utf-8")
    return waarschuwingen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("bestanden", nargs="+", type=Path, help="Factuur (PDF of tekst)")
    parser.add_argument("-o", "--output", type=Path, help=(
        "Uitvoerbestand. Bij meerdere invoerbestanden: een map "
        "(bestandsnamen blijven behouden, met -anoniem.txt). "
        "Standaard: naast het invoerbestand, als <naam>-anoniem.txt."
    ))
    parser.add_argument("--naam", help="Volledige naam op de factuur, bv. 'Mevr. Marleen De Beck'")
    parser.add_argument("--straat", help="Straat + huisnummer, bv. 'Tramstraat 40'")
    parser.add_argument("--postcode", help="Postcode, bv. '9220'")
    parser.add_argument("--gemeente", help="Gemeente, bv. 'Moerzeke'")
    parser.add_argument("--klantnummer", help="Klantnummer, los van het gelabelde veld op de factuur")
    parser.add_argument(
        "--extra", action="append", default=[],
        help="Extra losse term om te schrappen (meermaals te gebruiken)",
    )
    args = parser.parse_args(argv)

    extra_termen = list(args.extra)
    for waarde in (args.naam, args.straat, args.postcode, args.gemeente, args.klantnummer):
        if waarde:
            extra_termen.append(waarde)
    if args.postcode and args.gemeente:
        extra_termen.append(f"{args.postcode} {args.gemeente}")
    if args.straat and args.postcode and args.gemeente:
        extra_termen.append(f"{args.straat} {args.postcode} {args.gemeente}")

    if args.output and len(args.bestanden) > 1:
        args.output.mkdir(parents=True, exist_ok=True)

    alle_waarschuwingen: list[str] = []
    for bestand in args.bestanden:
        if not bestand.exists():
            print(f"Bestand niet gevonden: {bestand}", file=sys.stderr)
            return 1

        if args.output and len(args.bestanden) > 1:
            doel = args.output / f"{bestand.stem}-anoniem.txt"
        elif args.output:
            doel = args.output
        else:
            doel = bestand.with_name(f"{bestand.stem}-anoniem.txt")

        waarschuwingen = _verwerk_bestand(bestand, doel, extra_termen)
        print(f"{bestand} -> {doel}")
        alle_waarschuwingen.extend(waarschuwingen)

    for waarschuwing in dict.fromkeys(alle_waarschuwingen):  # uniek, volgorde behouden
        print(f"Let op: {waarschuwing}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
