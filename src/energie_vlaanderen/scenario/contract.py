""""Wat als ik in het verleden een ander (type) contract had genomen?"

`Kostberekening` kent de contractwissel- en tariefkaartbevriezingsmachinerie
al (`Leveringscontract.prijs_bevriest`/`peil_tariefkaart()`,
`periodes.snijd()`): een hypothetisch contract voor dezelfde periode geeft ze
gewoon mee aan `dataclasses.replace(dossier, contracten=...)`, en de rest van
de pijplijn kiest vanzelf de juiste historische tariefkaart of maandsnapshot.
Er komt hier dus geen nieuwe rekenregel bij — alleen dossiersurgerie.

**De bestaande contractgrenzen blijven bewaard.** `periodes.snijd()` knipt
o.a. op elke contractwissel (`contractgrenzen()`); een `Verbruiksopgave` in
het dossier hoeft niet met die knip samen te vallen, maar in de praktijk doet
ze dat vaak wél omdat de opgaveperiodes uit dezelfde afrekeningen komen als de
contractwissels. Verving deze klasse alle contracten door één doorlopend
hypothetisch contract, dan verdween die knip: twee opgaven die elk bij hun
eigen contractperiode hoorden, overlapten dan plots dezelfde, bredere
deelperiode, en `Kostberekening._opgave_voor()` weigert terecht te kiezen
tussen twee opgaven die hetzelfde venster claimen. Vandaar dat `pas_toe()`
**elk bestaand contract apart vervangt, met zijn eigen `geldig_van`/
`geldig_tot`** — hetzelfde aantal contracten, dezelfde knippunten, enkel
leverancier/product/contracttype anders.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Optional
from uuid import uuid4

from energie_vlaanderen.gebruikers.models import Contracttype, EnergieType, Leveringscontract
from energie_vlaanderen.gebruikers.toml_io import Dossier
from energie_vlaanderen.scenario.basis import Scenario


@dataclass
class AnderContractScenario(Scenario):
    """Vervangt de contracten van één aansluitingspunt door een hypothetisch
    contract, over de volledige berekende periode.

    Zonder `geldig_van`/`geldig_tot` geldt het hypothetische contract over het
    hele venster van `voer_uit(van, tot)`, verdeeld over exact dezelfde
    contractperiodes als het dossier al had (zie de moduledocstring) — precies
    wat "had ik toen dit contract genomen" bedoelt. Geef ze wel mee om een
    aangepast venster te gebruiken (bv. één doorlopend contract in plaats van
    de bestaande opeenvolgende contracten); let er dan zelf op dat eventuele
    `Verbruiksopgave`-grenzen binnen dat venster blijven samenvallen met een
    knippunt (een tariefjaar- of heffingengrens bijvoorbeeld), anders weigert
    de berekening met "meerdere verbruiksopgaven overlappen".
    """

    energie_type: EnergieType
    leverancier: str
    product: str
    contracttype: Contracttype
    geldig_van: Optional[date] = None
    geldig_tot: Optional[date] = None
    tariefkaart_geldig_van: Optional[date] = None
    injectie_product: str = ""
    vreg_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.naam:
            self.naam = f"Ander contract: {self.leverancier} — {self.product}"
        if not self.omschrijving:
            self.omschrijving = (
                f"Wat als {self.energie_type} liep via {self.leverancier} "
                f"({self.product}, {self.contracttype}) in plaats van het "
                "bestaande contract?"
            )

    def _hypothetisch_contract(
        self, punt_id, *, geldig_van: date, geldig_tot: Optional[date],
    ) -> Leveringscontract:
        return Leveringscontract(
            aansluitingspunt_id=punt_id,
            leverancier=self.leverancier,
            product=self.product,
            contracttype=self.contracttype,
            geldig_van=geldig_van,
            geldig_tot=geldig_tot,
            tariefkaart_geldig_van=self.tariefkaart_geldig_van,
            injectie_product=self.injectie_product,
            vreg_id=self.vreg_id,
            bron="scenario:ander_contract",
            id=uuid4(),
        )

    def pas_toe(self, dossier: Dossier) -> Dossier:
        punt = dossier.punt(self.energie_type)
        if punt is None:
            raise ValueError(
                f"Dit dossier heeft geen aansluitingspunt voor {self.energie_type}."
            )

        bestaande_contracten = dossier.contracten_van(punt)

        if self.geldig_van is not None or self.geldig_tot is not None:
            # Expliciet venster: één contract, zoals gevraagd. De oproeper is
            # dan zelf verantwoordelijk voor de opgave-uitlijning (zie de
            # docstring hierboven).
            van = self.geldig_van or min(
                (c.geldig_van for c in bestaande_contracten), default=date(1970, 1, 1),
            )
            hypothetische_contracten = (
                self._hypothetisch_contract(punt.id, geldig_van=van, geldig_tot=self.geldig_tot),
            )
        elif bestaande_contracten:
            # Standaardpad: elk bestaand contract 1-op-1 vervangen, met zijn
            # eigen periode — de contractgrenzen en dus de opgave-uitlijning
            # blijven ongewijzigd.
            hypothetische_contracten = tuple(
                self._hypothetisch_contract(
                    punt.id, geldig_van=c.geldig_van, geldig_tot=c.geldig_tot,
                )
                for c in bestaande_contracten
            )
        else:
            # Geen bestaand contract om te spiegelen: één contract over het
            # hele venster is dan het enige zinvolle antwoord.
            hypothetische_contracten = (
                self._hypothetisch_contract(punt.id, geldig_van=date(1970, 1, 1), geldig_tot=None),
            )

        overige_contracten = tuple(
            c for c in dossier.contracten if c.aansluitingspunt_id != punt.id
        )
        return replace(dossier, contracten=overige_contracten + hypothetische_contracten)
