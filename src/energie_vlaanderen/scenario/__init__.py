"""OO-API voor "wat als"-scenario's: ander contract, batterij, zonnepanelen,
elektrische wagen, warmtepomp.

Elk scenario rekent een bestaand dossier (de basislijn) en een gewijzigd
dossier af tegen dezelfde rekenengine
(`gebruikers.orchestratie.bereken_dossier()`, ook gebruikt door
`gebruiker bereken`), en geeft het verschil terug met volledige kostendetail
per energiedrager en per deelperiode — niet enkel een eindbedrag.

Typisch gebruik:

    from datetime import date
    from energie_vlaanderen.gebruikers.toml_io import lees_dossier
    from energie_vlaanderen.gebruikers.models import Contracttype, EnergieType
    from energie_vlaanderen.scenario import AnderContractScenario, opslag

    dossier = lees_dossier("gebruiker.toml", project_root=...)
    scenario = AnderContractScenario(
        energie_type=EnergieType.ELEKTRICITEIT,
        leverancier="Bolt", product="Bolt Variabel",
        contracttype=Contracttype.VARIABEL,
    )
    resultaat = scenario.voer_uit(
        dossier, conn=conn, settings=settings,
        van=date(2025, 1, 1), tot=date(2026, 1, 1),
    )
    opslag.sla_op(resultaat, "data/simulaties/ander_contract.json")

`vergelijk_contracten()` doet hetzelfde voor een hele lijst kandidaten tegen
één gedeelde basislijn — "vergelijken van contracten" op dossierniveau, in
aanvulling op de lichtere `energie_vlaanderen.simulatie`-mini-API die een los
product zonder dossiercontext doorrekent.

Batterij-/PV-/EV-/warmtepompscenario's (`scenario.batterij`,
`scenario.zonnepaneel`, `scenario.elektrische_wagen`, `scenario.warmtepomp`)
volgen dezelfde vorm, maar wijzigen ook het *volume*: ze simuleren de
fysieke impact via `calculation.dispatch` (op het SPP-/SLP-EX-/RLP0-profiel of
een echte Fluvius-meting) en geven de resulterende reeks als gesimuleerde
meting mee aan de herberekening, in plaats van enkel het dossier te wijzigen.
"""
from __future__ import annotations

from energie_vlaanderen.scenario.basis import Scenario, ScenarioResultaat
from energie_vlaanderen.scenario.batterij import BatterijScenario
from energie_vlaanderen.scenario.contract import AnderContractScenario
from energie_vlaanderen.scenario.context import ScenarioContext, open_scenario
from energie_vlaanderen.scenario.elektrische_wagen import ElektrischeWagenScenario
from energie_vlaanderen.scenario.vergelijk import vergelijk_contracten
from energie_vlaanderen.scenario.warmtepomp import WarmtepompScenario
from energie_vlaanderen.scenario.zonnepaneel import ZonnepaneelScenario

__all__ = [
    "AnderContractScenario",
    "BatterijScenario",
    "ElektrischeWagenScenario",
    "Scenario",
    "ScenarioContext",
    "ScenarioResultaat",
    "WarmtepompScenario",
    "ZonnepaneelScenario",
    "open_scenario",
    "vergelijk_contracten",
]
