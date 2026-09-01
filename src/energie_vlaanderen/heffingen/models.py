"""Domain-modellen voor heffingen en btw (manifest.md §8).

Alle bedragen zijn `Decimal` — nooit `float` (Manifest 3.0-regel).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class AccijnsSchijf:
    """Eén degressieve verbruiksschijf van de bijzondere accijns/energiebijdrage.

    `tot_mwh=None` betekent: geen bovengrens (hoogste schijf).

    `geldig_vanaf` (ISO-datum) is verplicht: de bijzondere accijns is sinds de
    hervorming van 2023 geen vast bedrag meer maar een reeks regimes met een
    ingangsdatum — 47,4811 EUR/MWh vanaf 01/07/2023, 46,00 vanaf 01/08/2026, en
    verder dalend tot 2029. Een tabel zonder tijdsas geeft voor élk jaar
    hetzelfde (dus meestal verkeerde) antwoord.
    """

    klantcategorie: str
    van_mwh: Decimal
    tot_mwh: Optional[Decimal]
    accijns_eur_mwh: Decimal
    bijzondere_accijns_eur_mwh: Decimal
    energiebijdrage_eur_mwh: Decimal
    geldig_vanaf: date
    # False = overgenomen uit een secundaire bron en nog niet tegen een
    # officiële publicatie of tegen vtest.be gelegd. Het cijfer wordt gebruikt,
    # maar `audit heffingen` rapporteert het apart.
    geverifieerd: bool = False
    bron: str = ""


@dataclass(frozen=True)
class AccijnsTabel:
    energievorm: str
    bron: str
    schijven: tuple[AccijnsSchijf, ...]


@dataclass(frozen=True)
class EnergiefondsTarief:
    jaar: int
    spanningsniveau: str  # "laag" | "midden" | "hoog"
    klantcategorie: str  # "" voor midden/hoog (geen onderscheid)
    eur_per_maand: Decimal
    bron: str


@dataclass(frozen=True)
class BtwTarief:
    component: str
    percentage: Decimal
    vrijgesteld: bool
    geldig_vanaf: str
    bron: str
