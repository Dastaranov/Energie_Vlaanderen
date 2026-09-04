"""Wat de rekenengine van een gegevensbron vraagt.

`Calculator` en `Kostberekening` waren getypeerd op `DataRepository`, de
CSV-lezer. Toen `DbDataRepository` erbij kwam werkte dat alleen doordat de twee
toevallig dezelfde methodes hadden — de uitwisselbaarheid was nergens
vastgelegd, en niets zou gemeld hebben als een van beide was gaan afwijken.

Dit protocol legt de afspraak vast. Het is bewust klein: het beschrijft precies
wat de berekening aanraakt en geen letter meer. Wie een derde bron wil bouwen —
een testdubbel, een leescache, een replica — heeft hieraan genoeg.

De regel die eronder ligt: **de berekening komt uit de code, de data uit de
databank.** Wisselt de bron, dan verandert er niets aan de rekenregels; dat is
alleen waar zolang de bron een afgebakend contract heeft.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd

from energie_vlaanderen.domain.models import Product


@runtime_checkable
class TariefBron(Protocol):
    """De gegevensbron waarmee een kost berekend wordt."""

    @property
    def dnb(self) -> pd.DataFrame:
        """De nettarieven, met de kolomnamen van het VREG-werkboek.

        `Calculator.grid_cost()` filtert letterlijk op `Netbeheerder`,
        `Klanttype`, `Contracttype`, `Tarieftype`, `Tariefdetail`,
        `Tariefnotering` en `Prijs_num`. Een bron die die namen niet levert,
        laat de netkost stil op nul uitkomen — dat is echt gebeurd.
        """

    @property
    def tariefjaar(self) -> int | None:
        """Het tariefjaar waar `dnb` bij hoort.

        De tariefrijen dragen zelf geen datum, dus aan de data is niet te zien
        of ze bij 2025 of 2026 horen. `Kostberekening` toetst dit per
        deelperiode: zonder die controle geeft een berekening over 2025 met de
        tarieven van 2026 een plausibel ogend en verkeerd bedrag.
        """

    def products(
        self,
        year: int,
        month: int,
        segment: str,
        *,
        energy: str = ...,
        direction: str = ...,
    ) -> list[Product]:
        """De producten van één maand.

        De maand is een parameter en geen eigenschap van de bron: een vast
        contract rekent met de snapshot van de maand waarin de tariefkaart
        bevroor, een variabel contract met die van de deelperiode zelf.
        """

    def dnb_for(
        self,
        postcode: str,
        gemeente: str = ...,
        energie_type: str = ...,
    ) -> tuple[str, str]:
        """De netbeheerder op dit adres, als `(naam, code)`.

        `gemeente` is nodig zodra één postcode meerdere netbeheerders kent;
        daar hoort een bron te weigeren in plaats van te gokken.
        """
