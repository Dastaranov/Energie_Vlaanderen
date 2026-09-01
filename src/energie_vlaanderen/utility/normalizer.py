from __future__ import annotations
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional
import pandas as pd
from energie_vlaanderen.utility.constants import CENT, D

NULL_TOKENS = {"", "nan", "none", "null", "(empty)", "n/a", "na"}
MOJIBAKE = {"�": "€", "â‚¬": "€", "\u00a0": " ", "\ufeff": ""}

def clean_text(value: Any) -> str:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    text = str(value)
    for bad, good in MOJIBAKE.items():
        text = text.replace(bad, good)
    return re.sub(r"\s+", " ", text).strip()

def nullify(value: Any) -> Optional[str]:
    text = clean_text(value)
    return None if text.casefold() in NULL_TOKENS else text

def dec(value: Any, default: Optional[Decimal] = None) -> Optional[Decimal]:
    text = nullify(value)
    if text is None:
        return default
    s = text.replace("€", "").replace(" ", "")
    if "," in s and "." in s:
        # Belgische notatie: punt als duizendtalseparator, komma als decimaalteken.
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    s = re.sub(r"[^0-9eE+.-]", "", s)
    try:
        return D(s)
    except InvalidOperation:
        return default

def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)

def norm(value: Any) -> str:
    return clean_text(value)


# VREG schrijft de leverancier soms als merknaam en soms als merknaam met een
# annotatie erachter: "ENGIE" naast "ENGIE (handelsnaam van Electrabel)". De
# bulk-export gebruikt beide vormen door elkaar, de live scrape van vtest.be
# vrijwel altijd de lange. Zonder normalisatie worden dat twee leveranciers en
# raken de producten van één leverancier over twee records verdeeld.
#
# Er bestaan twee soorten annotatie, met verschillende betekenis:
#
#   "X (handelsnaam van Y)"  X verkoopt onder juridische entiteit Y
#   "X (voorheen Y)"         X heette vroeger Y
#
# Ze horen niet op één hoop: de eerste zegt iets over de bedrijfsstructuur van
# vandaag, de tweede over het verleden van de naam. Beide worden uit de
# identiteit gehaald, maar apart bewaard.
_ANNOTATIES = (
    ("handelsnaam", re.compile(r"\s*\(handelsnaam van (?P<waarde>[^)]+)\)\s*$", re.IGNORECASE)),
    ("voorheen", re.compile(r"\s*\(voorheen (?P<waarde>[^)]+)\)\s*$", re.IGNORECASE)),
)

# Elke andere afsluitende haakjesgroep is een annotatie die we nog niet kennen.
# Die stil in de naam laten staan zou een nieuwe schrijfwijze een eigen
# leverancier maken; we melden ze daarom.
_ONBEKENDE_ANNOTATIE = re.compile(r"\s*\((?P<inhoud>[^)]+)\)\s*$")


@dataclass(frozen=True)
class Leveranciersnaam:
    """Een leveranciersnaam uit de VREG-data, ontleed.

    `naam` is de identiteit — het merk waaronder verkocht wordt.
    `juridische_entiteit` en `voormalige_naam` zijn eigenschappen daarvan.
    """

    naam: str
    juridische_entiteit: Optional[str] = None
    voormalige_naam: Optional[str] = None
    # Een afsluitende haakjesgroep die we niet herkennen. Blijft in `naam`
    # staan (weglaten zou informatie verzinnen), maar is opvraagbaar zodat de
    # importer erover kan waarschuwen.
    onbekende_annotatie: Optional[str] = None


def ontleed_leveranciersnaam(value: Any) -> Leveranciersnaam:
    """Haal merknaam en annotaties uit elkaar.

    Alleen expliciete, bekende annotaties worden weggenomen: die duiden
    dezelfde commerciële naam aan, dus wegnemen voegt niets samen wat niet al
    hetzelfde was. Verdergaande gelijkstelling zou gokwerk zijn — "Belvus" en
    "Belvus Energie" blijven daarom apart, net als 'Wind voor "A"' en Aspiravi
    Energy, dat wel dezelfde juridische entiteit is maar een ander merk.

    Op de export van augustus 2026 brengt dit 40 schrijfwijzen terug tot 34
    leveranciers, waarvan elke samenvoeging een merknaam met en zonder
    achtervoegsel betreft.
    """
    naam = clean_text(value)
    velden: dict[str, Optional[str]] = {
        "juridische_entiteit": None,
        "voormalige_naam": None,
    }
    sleutel_per_soort = {
        "handelsnaam": "juridische_entiteit",
        "voorheen": "voormalige_naam",
    }

    # Meerdere annotaties achter elkaar kunnen voorkomen; blijf strippen
    # zolang er een bekende op het eind staat.
    while True:
        for soort, patroon in _ANNOTATIES:
            match = patroon.search(naam)
            if match:
                velden[sleutel_per_soort[soort]] = match.group("waarde").strip()
                naam = naam[: match.start()].strip()
                break
        else:
            break

    onbekend = None
    rest = _ONBEKENDE_ANNOTATIE.search(naam)
    if rest:
        onbekend = rest.group("inhoud").strip()

    return Leveranciersnaam(
        naam=naam,
        juridische_entiteit=velden["juridische_entiteit"],
        voormalige_naam=velden["voormalige_naam"],
        onbekende_annotatie=onbekend,
    )


def split_leveranciersnaam(value: Any) -> tuple[str, Optional[str]]:
    """Kortere vorm van `ontleed_leveranciersnaam` voor het gangbare geval."""
    ontleed = ontleed_leveranciersnaam(value)
    return ontleed.naam, ontleed.juridische_entiteit


def leverancier_sleutel(value: Any) -> str:
    """Sleutel om leveranciersnamen op te vergelijken.

    Naast de annotaties verschilt ook het hoofdlettergebruik per rij ("Dots
    Energy" naast "Dots energy"), dus de sleutel is kleingeschreven.
    """
    return ontleed_leveranciersnaam(value).naam.casefold()
