"""Leest handmatig onderhouden heffingen-/btw-masterdata uit `config/heffingen/`.

Er is (nog) geen scrapebare bron voor heffingen — in tegenstelling tot vtest/
tariffs volgt dit package dus het patroon van `market/entsoe.py`: lokale,
versiegebonden data inlezen, geen download-pipeline.

Ontbrekende data leidt altijd tot een harde `HeffingenError` in plaats van een
stille 0 (manifest.md §12: "Ontbrekend verplicht tarief: berekening stoppen").
"""
from __future__ import annotations

import tomllib
from decimal import Decimal
from pathlib import Path
from typing import Optional

from energie_vlaanderen.heffingen.models import (
    AccijnsSchijf,
    AccijnsTabel,
    BtwTarief,
    EnergiefondsTarief,
)
from energie_vlaanderen.utility.constants import D

ACCIJNS_BESTAND = "bijzondere_accijns_elektriciteit.toml"
ENERGIEFONDS_BESTAND = "bijdrage_energiefonds.toml"
BTW_BESTAND = "btw.toml"


class HeffingenError(RuntimeError):
    """Verplichte heffingendata ontbreekt of is niet eenduidig."""


def _dec(value: str) -> Decimal:
    return D(str(value))


def _dec_opt(value: object) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    return D(str(value))


class HeffingenRepository:
    def __init__(
        self,
        accijns_tabellen: dict[str, AccijnsTabel],
        energiefonds: tuple[EnergiefondsTarief, ...],
        btw: tuple[BtwTarief, ...],
    ) -> None:
        self._accijns = accijns_tabellen
        self._energiefonds = energiefonds
        self._btw = btw

    def accijns_tabellen(self) -> dict[str, AccijnsTabel]:
        """Publieke accessor voor accijns-tabelgegevens (voor DB-import)."""
        return self._accijns

    def energiefonds_tarieven(self) -> tuple[EnergiefondsTarief, ...]:
        """Publieke accessor voor energiefonds-tarievengegevens (voor DB-import)."""
        return self._energiefonds

    def btw_tarieven(self) -> tuple[BtwTarief, ...]:
        """Publieke accessor voor btw-tarievengegevens (voor DB-import)."""
        return self._btw

    @classmethod
    def load(cls, config_dir: Path) -> "HeffingenRepository":
        accijns = cls._load_accijns(config_dir / ACCIJNS_BESTAND)
        energiefonds = cls._load_energiefonds(config_dir / ENERGIEFONDS_BESTAND)
        btw = cls._load_btw(config_dir / BTW_BESTAND)
        return cls(
            accijns_tabellen={accijns.energievorm: accijns},
            energiefonds=tuple(energiefonds),
            btw=tuple(btw),
        )

    @staticmethod
    def _load_accijns(path: Path) -> AccijnsTabel:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
        schijven = tuple(
            AccijnsSchijf(
                klantcategorie=row["klantcategorie"],
                van_mwh=_dec(row["van_mwh"]),
                tot_mwh=_dec_opt(row.get("tot_mwh")),
                accijns_eur_mwh=_dec(row["accijns_eur_mwh"]),
                bijzondere_accijns_eur_mwh=_dec(row["bijzondere_accijns_eur_mwh"]),
                energiebijdrage_eur_mwh=_dec(row["energiebijdrage_eur_mwh"]),
            )
            for row in raw["schijf"]
        )
        return AccijnsTabel(energievorm=raw["energievorm"], bron=raw["bron"], schijven=schijven)

    @staticmethod
    def _load_energiefonds(path: Path) -> list[EnergiefondsTarief]:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
        bron = raw["bron"]
        return [
            EnergiefondsTarief(
                jaar=row["jaar"],
                spanningsniveau=row["spanningsniveau"],
                klantcategorie=row.get("klantcategorie", ""),
                eur_per_maand=_dec(row["eur_per_maand"]),
                bron=bron,
            )
            for row in raw["tarief"]
        ]

    @staticmethod
    def _load_btw(path: Path) -> list[BtwTarief]:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
        bron = raw["bron"]
        return [
            BtwTarief(
                component=row["component"],
                percentage=_dec(row["percentage"]),
                vrijgesteld=bool(row.get("vrijgesteld", False)),
                geldig_vanaf=row["geldig_vanaf"],
                bron=bron,
            )
            for row in raw["tarief"]
        ]

    def bereken_accijns_en_energiebijdrage(
        self, energievorm: str, klantcategorie: str, jaarverbruik_kwh: Decimal
    ) -> tuple[Decimal, Decimal]:
        """Progressieve (degressieve) schijvenberekening.

        Geeft `(bijzondere_accijns_totaal, energiebijdrage_totaal)` in EUR/jaar
        terug. De "gewone" accijns (`accijns_eur_mwh`, vandaag overal 0) wordt
        meegeteld in de bijzondere-accijnscomponent — beide zijn accijnzen op
        dezelfde grondslag en worden in `Cost.levies` toch samengeteld; apart
        houden zou enkel een derde, vandaag altijd-nul waarde toevoegen.
        """
        tabel = self._accijns.get(energievorm)
        if tabel is None:
            raise HeffingenError(
                f"Geen bijzondere-accijnsdata voor energievorm '{energievorm}' "
                f"(config/heffingen/{ACCIJNS_BESTAND})."
            )
        schijven = [s for s in tabel.schijven if s.klantcategorie == klantcategorie]
        if not schijven:
            raise HeffingenError(
                f"Geen bijzondere-accijnsschijven voor klantcategorie "
                f"'{klantcategorie}' bij energievorm '{energievorm}' "
                f"(config/heffingen/{ACCIJNS_BESTAND})."
            )

        verbruik_mwh = jaarverbruik_kwh / D("1000")
        bijzondere_totaal = D("0")
        energiebijdrage_totaal = D("0")
        for schijf in sorted(schijven, key=lambda s: s.van_mwh):
            bovengrens = schijf.tot_mwh if schijf.tot_mwh is not None else verbruik_mwh
            overlap = min(bovengrens, verbruik_mwh) - schijf.van_mwh
            if overlap <= 0:
                continue
            bijzondere_totaal += overlap * (
                schijf.bijzondere_accijns_eur_mwh + schijf.accijns_eur_mwh
            )
            energiebijdrage_totaal += overlap * schijf.energiebijdrage_eur_mwh
        return bijzondere_totaal, energiebijdrage_totaal

    def energiefonds_per_jaar(
        self, spanningsniveau: str, klantcategorie: str, jaar: int
    ) -> Decimal:
        for tarief in self._energiefonds:
            if (
                tarief.spanningsniveau == spanningsniveau
                and tarief.klantcategorie == klantcategorie
                and tarief.jaar == jaar
            ):
                return tarief.eur_per_maand * D("12")
        raise HeffingenError(
            f"Geen Bijdrage Energiefonds-tarief voor spanningsniveau="
            f"'{spanningsniveau}', klantcategorie='{klantcategorie}', jaar="
            f"{jaar} (config/heffingen/{ENERGIEFONDS_BESTAND})."
        )

    def btw_percentage(self, component: str) -> Decimal:
        for tarief in self._btw:
            if tarief.component == component:
                return D("0") if tarief.vrijgesteld else tarief.percentage
        raise HeffingenError(
            f"Geen btw-tarief voor component '{component}' "
            f"(config/heffingen/{BTW_BESTAND})."
        )
