from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional
from .constants import D

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
    geschatte_maandpiek_kw: Decimal = D("2.5")
    kwartier_csv: Optional[Path] = None
    @property
    def afname_kwh(self): return self.afname_dag_kwh + self.afname_nacht_kwh
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
