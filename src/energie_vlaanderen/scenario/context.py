"""Eén geopende databankverbinding + dossier, met de scenario's eromheen.

Zelfde ergonomie als `energie_vlaanderen.simulatie.open_simulatie()`, maar op
het niveau van een volledig dossier in plaats van één los product: `dossier`
wordt hier al ingelezen (met het postcode->netbeheerderregister uit de
databank, dezelfde regel als `cli/gebruikers.py::_lees()` volgt), zodat een
webinterface-endpoint of een script niet zelf de opzet moet herhalen.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Optional, Union

import sqlalchemy as sa

from energie_vlaanderen.gebruikers.orchestratie import DossierResultaat, bereken_dossier
from energie_vlaanderen.gebruikers.toml_io import Dossier, lees_dossier
from energie_vlaanderen.infrastructure.db.connection import get_engine
from energie_vlaanderen.settings import Settings

if TYPE_CHECKING:
    from energie_vlaanderen.scenario.basis import Scenario, ScenarioResultaat


@dataclass
class ScenarioContext:
    """Facade rond `bereken_dossier()`/`Scenario.voer_uit()`, met de databank
    en het dossier al geopend."""

    conn: sa.Connection
    settings: Settings
    dossier: Dossier

    def bereken(self, van: date, tot: date, **kwargs) -> DossierResultaat:
        """De basislijn: het (ongewijzigde) dossier doorgerekend over `[van, tot)`."""
        return bereken_dossier(self.dossier, conn=self.conn, settings=self.settings, van=van, tot=tot, **kwargs)

    def voer_scenario_uit(
        self, scenario: "Scenario", van: date, tot: date,
        *, basislijn: Optional[DossierResultaat] = None,
    ) -> "ScenarioResultaat":
        return scenario.voer_uit(
            self.dossier, conn=self.conn, settings=self.settings, van=van, tot=tot,
            basislijn=basislijn,
        )


@contextmanager
def open_scenario(
    dossier_pad: Union[str, Path],
    *,
    project_root: Optional[Path] = None,
) -> Iterator[ScenarioContext]:
    """Open een databankverbinding en lees `dossier_pad` in, klaar voor
    `ctx.bereken(...)`/`ctx.voer_scenario_uit(...)`.

    De verbinding sluit automatisch bij het verlaten van het `with`-blok —
    zelfde discipline als `simulatie.open_simulatie()`.
    """
    settings = Settings.load(project_root=project_root)
    engine = get_engine(settings.project_root)
    try:
        with engine.connect() as conn:
            from energie_vlaanderen.data.db_repository import (
                DbDataRepositoryError,
                netbeheerders_uit_databank,
            )

            try:
                netbeheerders = netbeheerders_uit_databank(conn)
            except DbDataRepositoryError:
                netbeheerders = None

            dossier = lees_dossier(
                Path(dossier_pad), project_root=settings.project_root,
                netbeheerders=netbeheerders,
            )
            yield ScenarioContext(conn=conn, settings=settings, dossier=dossier)
    finally:
        engine.dispose()
