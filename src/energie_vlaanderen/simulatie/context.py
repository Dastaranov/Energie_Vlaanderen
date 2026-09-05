"""Eén geopende databankverbinding, met de repositories eromheen.

`open_simulatie()` is de enige plek waar deze mini-API een `Engine` opent.
Alles daarna — opzoeken, doorrekenen — werkt op de reeds geopende
`SimulatieContext` en opent zelf geen nieuwe verbinding, zodat een reeks
opzoekingen en berekeningen binnen één `with`-blok de caches van
`DbDataRepository` (nettarieven, netbeheerderregister) hergebruikt in
plaats van ze telkens opnieuw te bevragen.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Optional

import sqlalchemy as sa

from energie_vlaanderen.calculation.calculator import Calculator
from energie_vlaanderen.data.db_repository import DbDataRepository
from energie_vlaanderen.domain.models import Cost, Product, Profile
from energie_vlaanderen.heffingen.repository import HeffingenRepository
from energie_vlaanderen.infrastructure.db.connection import get_engine
from energie_vlaanderen.settings import Settings

if TYPE_CHECKING:
    from energie_vlaanderen.simulatie.catalogus import ContractMetadata, Leverancier


@dataclass
class SimulatieContext:
    """Facade rond `DbDataRepository`/`Calculator`/`HeffingenRepository`.

    De methodes hieronder zijn dunne doorverwijzingen naar de functies in
    `catalogus.py`/`berekenen.py` — ze bestaan voor het leesgemak
    (`sim.haal_contract(...)` in plaats van een aparte import), niet omdat
    er hier nog logica bijkomt.
    """

    conn: sa.Connection
    settings: Settings
    tariefjaar: int
    repo: DbDataRepository
    heffingen: HeffingenRepository
    calculator: Calculator

    def lijst_leveranciers(self) -> "list[Leverancier]":
        from energie_vlaanderen.simulatie.catalogus import lijst_leveranciers
        return lijst_leveranciers(self)

    def lijst_contracten(
        self,
        *,
        energie_type: Optional[str] = None,
        segment: Optional[str] = None,
        leverancier: Optional[str] = None,
        actief_op: Optional[date] = None,
        alleen_actueel: bool = True,
    ) -> "list[ContractMetadata]":
        from energie_vlaanderen.simulatie.catalogus import lijst_contracten
        return lijst_contracten(
            self, energie_type=energie_type, segment=segment, leverancier=leverancier,
            actief_op=actief_op, alleen_actueel=alleen_actueel,
        )

    def haal_contract(self, vreg_id: str, *, op_datum: Optional[date] = None) -> "ContractMetadata":
        from energie_vlaanderen.simulatie.catalogus import haal_contract
        return haal_contract(self, vreg_id, op_datum=op_datum)

    def lijst_producten(
        self, jaar: int, maand: int, segment: str, *,
        energy: str = "elektriciteit", direction: str = "afname",
    ) -> list[Product]:
        """De ruwe productenlijst van één maand, rechtstreeks van `DbDataRepository`."""
        return self.repo.products(jaar, maand, segment, energy=energy, direction=direction)

    def bereken_contract(
        self,
        *,
        leverancier: str,
        product_naam: str,
        jaar: int,
        maand: int,
        profiel: Profile,
        energie: str = "elektriciteit",
        prijs_type: Optional[str] = None,
        injectie_leverancier: Optional[str] = None,
        injectie_product_naam: Optional[str] = None,
        injectie_prijs_type: Optional[str] = None,
        sta_tariefjaarverschil: bool = False,
    ) -> Cost:
        from energie_vlaanderen.simulatie.berekenen import bereken_kost
        return bereken_kost(
            self, leverancier=leverancier, product_naam=product_naam, jaar=jaar,
            maand=maand, profiel=profiel, energie=energie, prijs_type=prijs_type,
            injectie_leverancier=injectie_leverancier,
            injectie_product_naam=injectie_product_naam,
            injectie_prijs_type=injectie_prijs_type,
            sta_tariefjaarverschil=sta_tariefjaarverschil,
        )


@contextmanager
def open_simulatie(
    *,
    tariefjaar: int,
    project_root: Optional[Path] = None,
    vat: Optional[Decimal] = None,
) -> Iterator[SimulatieContext]:
    """Open een databankverbinding en de repositories eromheen.

    `tariefjaar` bepaalt welke jaargang nettarieven `DbDataRepository.dnb`
    laadt — VREG stelt de distributienettarieven per kalenderjaar vast (zie
    CLAUDE.md "Het tariefjaar komt uit het werkboek, niet uit het
    versie-id"). Het jaar van de *producten* (leverancierskost) wordt apart
    meegegeven aan `lijst_producten`/`bereken_contract`, want dat is per
    maand beschikbaar en niet aan deze context gebonden.

    De verbinding sluit automatisch bij het verlaten van het `with`-blok.
    """
    settings = Settings.load(project_root=project_root)
    engine = get_engine(settings.project_root)
    heffingen = HeffingenRepository.load(settings.project_root / "config" / "heffingen")
    try:
        with engine.connect() as conn:
            repo = DbDataRepository(conn, tariefjaar=tariefjaar)
            calculator = (
                Calculator(repo, vat, heffingen) if vat is not None
                else Calculator(repo, heffingen=heffingen)
            )
            yield SimulatieContext(
                conn=conn, settings=settings, tariefjaar=tariefjaar,
                repo=repo, heffingen=heffingen, calculator=calculator,
            )
    finally:
        engine.dispose()
