from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional
from energie_vlaanderen.utility.constants import D

@dataclass(frozen=True)
class Profile:
    postcode: str
    gemeente: str = ""
    segment: str = "Woning"
    meter: str = "digitaal"
    afname_dag_kwh: Decimal = D("0")
    afname_nacht_kwh: Decimal = D("0")
    injectie_dag_kwh: Decimal = D("0")
    injectie_nacht_kwh: Decimal = D("0")
    omvormer_kva: Decimal = D("0")
    maandpieken_kw: tuple[Decimal, ...] = ()
    # Twee getallen die vroeger één getal waren, en dat is precies de fout die
    # ze scheidt: 2,5 kW is de wettelijke ondergrens van het capaciteitstarief
    # en 4,218 kW is een schatting van een werkelijke piek. Ze hadden allebei
    # de waarde 2,5, waardoor wie geen eigen maandpieken aanlevert per
    # definitie op de bodem rekende — een factuur die er plausibel uitzag en
    # ongeveer 86 EUR/jaar te laag was.
    #
    # 4,218 kW is teruggerekend uit de gescrapete capaciteitstarieven van alle
    # acht netbeheerders (2026-08-31): het is de piek waarmee vtest.be zijn
    # standaardwoning doorrekent. Dat maakt het geen natuurwet maar wel de
    # waarde waarmee de officiële vergelijkingstool van VREG rekent, en die
    # volgen we hier.
    geschatte_maandpiek_kw: Decimal = D("4.218")
    # De wettelijke ondergrens. Het capaciteitstarief rekent nooit met minder,
    # ook niet als de gemeten piek lager ligt. Staat hier als veld en niet als
    # constante in de calculator omdat het een tarifair gegeven is dat kan
    # wijzigen, en omdat een berekening moet kunnen zeggen wélke ondergrens ze
    # toegepast heeft.
    minimum_maandpiek_kw: Decimal = D("2.5")
    # Het exclusief-nachtregister is géén synoniem van "nacht" of "dal".
    #
    # Een tweevoudige meter splitst het verbruik in piek- en daluren; beide
    # krijgen het *normale* ODV-tarief. "Exclusief nacht" is een apart register
    # voor toestellen die alleen 's nachts draaien (accumulatieverwarming,
    # boiler) en heeft een eigen, lager ODV-tarief.
    #
    # Ze samenvoegen paste dat lagere tarief toe op het hele dalverbruik. Op een
    # echte afrekening — 4.218 kWh dal bij FMV 2025 — scheelde dat 35 EUR per
    # jaar te weinig netkost. Dit veld staat achteraan zodat bestaande
    # positionele aanroepen van `Profile(...)` niet stil verschuiven.
    afname_exclusief_nacht_kwh: Decimal = D("0")
    kwartier_csv: Optional[Path] = None
    @property
    def afname_kwh(self):
        return (
            self.afname_dag_kwh + self.afname_nacht_kwh + self.afname_exclusief_nacht_kwh
        )
    @property
    def injectie_kwh(self): return self.injectie_dag_kwh + self.injectie_nacht_kwh

@dataclass
class Product:
    year: int; month: int; segment: str; energy: str; direction: str
    supplier: str; name: str; kind: str
    components: dict[str, Decimal] = field(default_factory=dict)
    formulas: dict[str, dict[str, Any]] = field(default_factory=dict)
    source: str = ""

@dataclass
class Cost:
    supplier: Decimal = D("0"); grid: Decimal = D("0"); levies: Decimal = D("0")
    injection_credit: Decimal = D("0"); vat: Decimal = D("0")
    warnings: list[str] = field(default_factory=list)
    @property
    def total(self): return self.supplier + self.grid + self.levies + self.vat - self.injection_credit
