"""Contractvergelijking op dossierniveau: veel kandidaten, één basislijn.

Waar `energie_vlaanderen.simulatie` een los leverancier/product/maand doorrekent
zonder dossiercontext, rekent dit elke kandidaat af tegen het volledige dossier
van de gebruiker (met zijn eigen verbruik, meter, netbeheerder) — "vergelijken
van contracten" zoals de gebruiker het bedoelt: niet "wat kost dit product
gemiddeld", maar "wat zou *mijn* factuur zijn met dit product".

De basislijn wordt precies één keer berekend en voor elke kandidaat hergebruikt
— bij tien kandidaten tien keer minder databankwerk dan `Scenario.voer_uit()`
los aanroepen, én de garantie dat elke kandidaat tegen exact dezelfde basislijn
afgezet wordt.
"""
from __future__ import annotations

from datetime import date
from typing import Sequence

from energie_vlaanderen.gebruikers.orchestratie import bereken_dossier
from energie_vlaanderen.gebruikers.toml_io import Dossier
from energie_vlaanderen.scenario.basis import Scenario, ScenarioResultaat
from energie_vlaanderen.settings import Settings


def vergelijk_contracten(
    basis_dossier: Dossier,
    kandidaten: Sequence[Scenario],
    *,
    conn,
    settings: Settings,
    van: date,
    tot: date,
) -> list[ScenarioResultaat]:
    """Rekent elke kandidaat af tegen één gedeelde basislijn, gesorteerd op
    totaalkost (goedkoopste eerst)."""
    basislijn = bereken_dossier(basis_dossier, conn=conn, settings=settings, van=van, tot=tot)

    resultaten = [
        kandidaat.voer_uit(
            basis_dossier, conn=conn, settings=settings, van=van, tot=tot,
            basislijn=basislijn,
        )
        for kandidaat in kandidaten
    ]
    return sorted(resultaten, key=lambda r: r.totaal_scenario)
