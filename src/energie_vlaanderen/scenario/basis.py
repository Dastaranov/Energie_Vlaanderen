"""De generieke vorm van een "wat als"-scenario.

Een scenario beantwoordt telkens dezelfde vraag: "wat verandert er aan de kost
als ik dít anders had gedaan?" — een ander contract, een batterij erbij, een
zonnepaneel, een elektrische wagen, een warmtepomp. De machinerie is voor allen
gelijk: bereken het bestaande dossier (de basislijn), bouw een gewijzigd
dossier, bereken dat opnieuw, en verschil de twee. Alleen de wijziging zelf
verschilt per scenariotype — dat is wat `Scenario.pas_toe()` invult.

Dit bestand voegt bewust geen nieuwe rekenregel toe: elke berekening loopt via
`gebruikers.orchestratie.bereken_dossier()`, dezelfde functie die
`gebruiker bereken` gebruikt. Een scenario is dossiersurgerie plus een diff,
geen tweede rekenengine — precies de scheiding die ROADMAP.md §14
("fysieke en financiële modellen blijven gescheiden") voorschrijft: dit
bestand kent geen fysica, enkel `Dossier`s en `Berekening`s.

Elk resultaat draagt `Exactheidsklasse.SCENARIO` (Manifest §5.8: "exact,
gereconstrueerd, geschat of scenario") — ook als elke onderliggende
tariefopzoeking exact was. Een scenario is per definitie hypothetisch, en dat
moet je aan het resultaat kunnen zien, niet enkel aan de naam van de functie
die het teruggaf.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from energie_vlaanderen.gebruikers.berekening import Berekening
from energie_vlaanderen.gebruikers.models import Aanname, EnergieType, Exactheidsklasse
from energie_vlaanderen.gebruikers.orchestratie import DossierResultaat, bereken_dossier
from energie_vlaanderen.gebruikers.toml_io import Dossier
from energie_vlaanderen.settings import Settings
from energie_vlaanderen.utility.constants import D


@dataclass(frozen=True)
class ScenarioResultaat:
    """Basislijn, scenario en het verschil ertussen — met volledige kostendetail.

    `basislijn`/`scenario` zijn elk een `dict[EnergieType, Berekening]`: de
    volledige `Berekening` blijft bewaard (regels, componenten, aannames,
    waarschuwingen), niet enkel het totaal. "Kostprijs per gewenst contract,
    in detail" betekent hier dat er nooit alleen een eindbedrag teruggegeven
    wordt.
    """

    naam: str
    omschrijving: str
    basislijn: dict[EnergieType, Berekening]
    scenario: dict[EnergieType, Berekening]
    verschil_eur: dict[str, Decimal]
    exactheidsklasse: Exactheidsklasse
    aannames: tuple[Aanname, ...] = ()
    warnings: tuple[str, ...] = ()
    aangemaakt_op: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def totaal_basislijn(self) -> Decimal:
        return sum((b.totalen["totaal"] for b in self.basislijn.values()), D("0"))

    @property
    def totaal_scenario(self) -> Decimal:
        return sum((b.totalen["totaal"] for b in self.scenario.values()), D("0"))


def _totalen_per_type(resultaat: DossierResultaat) -> dict[EnergieType, Decimal]:
    return {punt.energie_type: r.totalen["totaal"] for punt, r in resultaat.resultaten}


def _berekeningen_per_type(resultaat: DossierResultaat) -> dict[EnergieType, Berekening]:
    return {punt.energie_type: r for punt, r in resultaat.resultaten}


class Scenario(ABC):
    """Eén hypothese over een gewijzigd dossier.

    `pas_toe()` bouwt een *nieuw* dossier — `Dossier` is een frozen dataclass,
    dus `dataclasses.replace()` is de enige manier om het te wijzigen, en het
    origineel kan nooit per ongeluk mee veranderen. Subklassen die ook het
    *volume* wijzigen (batterij, PV, EV, warmtepomp — zie `scenario.batterij`
    e.a.) overschrijven `voer_uit()` in plaats van enkel `pas_toe()`, want
    `bereken_dossier()` neemt een gesimuleerde meetreeks als apart argument en
    niet als deel van het dossier zelf.
    """

    naam: str = ""
    omschrijving: str = ""

    @abstractmethod
    def pas_toe(self, dossier: Dossier) -> Dossier:
        """Geeft een nieuw, gewijzigd dossier terug. Muteert `dossier` nooit."""

    def voer_uit(
        self,
        basis_dossier: Dossier,
        *,
        conn,
        settings: Settings,
        van: date,
        tot: date,
        basislijn: Optional[DossierResultaat] = None,
    ) -> ScenarioResultaat:
        """Berekent de basislijn (tenzij meegegeven), past het scenario toe,
        herberekent, en verschilt de twee.

        `basislijn` meegeven bespaart een herberekening wanneer meerdere
        scenario's tegen hetzelfde dossier afgezet worden (zie
        `scenario.vergelijk.vergelijk_contracten()`).
        """
        if basislijn is None:
            basislijn = bereken_dossier(
                basis_dossier, conn=conn, settings=settings, van=van, tot=tot,
            )

        gewijzigd_dossier = self.pas_toe(basis_dossier)
        scenario_resultaat = bereken_dossier(
            gewijzigd_dossier, conn=conn, settings=settings, van=van, tot=tot,
        )

        return self._verpak(basislijn, scenario_resultaat)

    def _verpak(
        self, basislijn: DossierResultaat, scenario_resultaat: DossierResultaat,
    ) -> ScenarioResultaat:
        basis_totalen = _totalen_per_type(basislijn)
        scenario_totalen = _totalen_per_type(scenario_resultaat)

        alle_types = set(basis_totalen) | set(scenario_totalen)
        verschil_eur: dict[str, Decimal] = {
            str(t): scenario_totalen.get(t, D("0")) - basis_totalen.get(t, D("0"))
            for t in alle_types
        }
        verschil_eur["totaal"] = sum(verschil_eur.values(), D("0"))

        exactheidsklasse = Exactheidsklasse.zwakste([
            basislijn.exactheidsklasse, scenario_resultaat.exactheidsklasse,
            Exactheidsklasse.SCENARIO,
        ])

        # Een punt dat niet doorgerekend kon worden verdwijnt niet stil: het
        # verschil hierboven is dan onvolledig (som over minder punten dan de
        # basislijn), en dat moet zichtbaar blijven — zie CLAUDE.md "Een fout
        # op het ene punt laat het andere niet vervallen". Vooral belangrijk
        # wanneer een puntsoort in de basislijn wél lukte en in het scenario
        # niet: het verschil lijkt dan kleiner (of groter) dan het is.
        mislukt_waarschuwingen = tuple(
            f"{soort} niet doorgerekend in het scenario: {melding}"
            for soort, melding in scenario_resultaat.mislukt
        ) + tuple(
            f"{soort} niet doorgerekend in de basislijn: {melding}"
            for soort, melding in basislijn.mislukt
        )

        return ScenarioResultaat(
            naam=self.naam or type(self).__name__,
            omschrijving=self.omschrijving,
            basislijn=_berekeningen_per_type(basislijn),
            scenario=_berekeningen_per_type(scenario_resultaat),
            verschil_eur=verschil_eur,
            exactheidsklasse=exactheidsklasse,
            aannames=tuple(
                a for _, r in scenario_resultaat.resultaten for a in r.aannames
            ),
            warnings=tuple(dict.fromkeys(
                mislukt_waarschuwingen
                + tuple(scenario_resultaat.meetwaarschuwingen)
                + tuple(w for _, r in scenario_resultaat.resultaten for w in r.warnings)
            )),
        )
