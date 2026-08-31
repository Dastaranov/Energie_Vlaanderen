"""Domain-modellen voor heffingen en btw (manifest.md §8).

Alle bedragen zijn `Decimal` — nooit `float` (Manifest 3.0-regel).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class AccijnsSchijf:
    """Eén degressieve verbruiksschijf van de bijzondere accijns/energiebijdrage.

    `tot_mwh=None` betekent: geen bovengrens (hoogste schijf).
    """

    klantcategorie: str
    van_mwh: Decimal
    tot_mwh: Optional[Decimal]
    accijns_eur_mwh: Decimal
    bijzondere_accijns_eur_mwh: Decimal
    energiebijdrage_eur_mwh: Decimal


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
