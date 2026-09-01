"""Leest handmatig onderhouden heffingen-/btw-masterdata uit `config/heffingen/`.

Er is (nog) geen scrapebare bron voor heffingen — in tegenstelling tot vtest/
tariffs volgt dit package dus het patroon van `market/entsoe.py`: lokale,
versiegebonden data inlezen, geen download-pipeline.

Ontbrekende data leidt altijd tot een harde `HeffingenError` in plaats van een
stille 0 (manifest.md §12: "Ontbrekend verplicht tarief: berekening stoppen").
"""
from __future__ import annotations

import tomllib
from datetime import date, datetime
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

# Eén bestand per energievorm: bijzondere_accijns_elektriciteit.toml,
# bijzondere_accijns_aardgas.toml, ... De energievorm staat in het bestand
# zelf, dus nieuwe bestanden vragen geen codewijziging.
ACCIJNS_PATROON = "bijzondere_accijns_*.toml"
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


def _datum(value: object, path: Path, row: object) -> date:
    """TOML geeft een kale datum al als `datetime.date` terug; een string
    accepteren we ook, zodat de bestanden met aanhalingstekens leesbaar
    blijven naast de andere velden (die allemaal string zijn om
    float-afronding te vermijden)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise HeffingenError(
            f"Ongeldige geldig_vanaf '{value}' in {path.name} (rij: {row})."
        ) from exc


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
        tabellen: dict[str, AccijnsTabel] = {}
        for path in sorted(config_dir.glob(ACCIJNS_PATROON)):
            tabel = cls._load_accijns(path)
            if tabel.energievorm in tabellen:
                raise HeffingenError(
                    f"Twee accijnsbestanden claimen energievorm "
                    f"'{tabel.energievorm}' (laatste: {path.name})."
                )
            tabellen[tabel.energievorm] = tabel
        if not tabellen:
            raise HeffingenError(
                f"Geen accijnsbestanden gevonden in {config_dir} "
                f"(patroon {ACCIJNS_PATROON})."
            )
        energiefonds = cls._load_energiefonds(config_dir / ENERGIEFONDS_BESTAND)
        btw = cls._load_btw(config_dir / BTW_BESTAND)
        return cls(
            accijns_tabellen=tabellen,
            energiefonds=tuple(energiefonds),
            btw=tuple(btw),
        )

    @staticmethod
    def _load_accijns(path: Path) -> AccijnsTabel:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
        bestandsbron = raw["bron"]
        schijven = tuple(
            AccijnsSchijf(
                klantcategorie=row["klantcategorie"],
                van_mwh=_dec(row["van_mwh"]),
                tot_mwh=_dec_opt(row.get("tot_mwh")),
                accijns_eur_mwh=_dec(row["accijns_eur_mwh"]),
                bijzondere_accijns_eur_mwh=_dec(row["bijzondere_accijns_eur_mwh"]),
                energiebijdrage_eur_mwh=_dec(row["energiebijdrage_eur_mwh"]),
                geldig_vanaf=_datum(row["geldig_vanaf"], path, row),
                geverifieerd=bool(row.get("geverifieerd", False)),
                bron=row.get("bron", bestandsbron),
            )
            for row in raw["schijf"]
        )
        return AccijnsTabel(energievorm=raw["energievorm"], bron=bestandsbron, schijven=schijven)

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

    def accijns_schijven(
        self, energievorm: str, klantcategorie: str, op_datum: date
    ) -> tuple[AccijnsSchijf, ...]:
        """De schijven die op `op_datum` van kracht zijn.

        De accijnstabellen zijn een reeks regimes: elke schijf draagt een
        `geldig_vanaf`. Het geldende regime is dat met de meest recente
        ingangsdatum die niet in de toekomst ligt; alle schijven met díe datum
        vormen samen de tabel. Regimes worden dus nooit vermengd — anders zou
        een oude schijfindeling gaten of overlappingen maken met een nieuwe.
        """
        tabel = self._accijns.get(energievorm)
        if tabel is None:
            raise HeffingenError(
                f"Geen bijzondere-accijnsdata voor energievorm '{energievorm}' "
                f"(verwacht config/heffingen/bijzondere_accijns_{energievorm}.toml)."
            )
        van_categorie = [s for s in tabel.schijven if s.klantcategorie == klantcategorie]
        if not van_categorie:
            beschikbaar = sorted({s.klantcategorie for s in tabel.schijven})
            raise HeffingenError(
                f"Geen bijzondere-accijnsschijven voor klantcategorie "
                f"'{klantcategorie}' bij energievorm '{energievorm}'. "
                f"Beschikbaar: {', '.join(beschikbaar)}."
            )

        van_kracht = [s for s in van_categorie if s.geldig_vanaf <= op_datum]
        if not van_kracht:
            vroegste = min(s.geldig_vanaf for s in van_categorie)
            raise HeffingenError(
                f"Geen bijzondere-accijnstarief voor {energievorm}/"
                f"{klantcategorie} op {op_datum.isoformat()}: de masterdata "
                f"begint pas op {vroegste.isoformat()}. Vul "
                f"config/heffingen/ aan in plaats van met een ouder tarief "
                f"te rekenen."
            )
        ingang = max(s.geldig_vanaf for s in van_kracht)
        return tuple(
            sorted(
                (s for s in van_kracht if s.geldig_vanaf == ingang),
                key=lambda s: s.van_mwh,
            )
        )

    def bereken_accijns_en_energiebijdrage(
        self,
        energievorm: str,
        klantcategorie: str,
        jaarverbruik_kwh: Decimal,
        op_datum: date,
    ) -> tuple[Decimal, Decimal]:
        """Progressieve (degressieve) schijvenberekening op de tarieven die op
        `op_datum` van kracht zijn.

        Geeft `(bijzondere_accijns_totaal, energiebijdrage_totaal)` in EUR/jaar
        terug. De "gewone" accijns (`accijns_eur_mwh`, vandaag overal 0) wordt
        meegeteld in de bijzondere-accijnscomponent — beide zijn accijnzen op
        dezelfde grondslag en worden in `Cost.levies` toch samengeteld; apart
        houden zou enkel een derde, vandaag altijd-nul waarde toevoegen.
        """
        schijven = self.accijns_schijven(energievorm, klantcategorie, op_datum)

        verbruik_mwh = jaarverbruik_kwh / D("1000")
        bijzondere_totaal = D("0")
        energiebijdrage_totaal = D("0")
        for schijf in schijven:
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
