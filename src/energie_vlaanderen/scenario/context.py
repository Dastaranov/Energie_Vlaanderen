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
        *, basislijn: Optional[DossierResultaat] = None, bewaar: bool = True,
    ) -> "ScenarioResultaat":
        """Voert `scenario` uit en schrijft het resultaat automatisch weg naar
        de databank (`bewaar=False` schakelt dat uit — bv. voor een
        rooktest die de simulatietabel niet wil vervuilen).

        De basislijn wordt hier (en niet pas binnen `Scenario.voer_uit()`)
        berekend zodra ze niet is meegegeven, want `DossierResultaat.dataversie`
        is nodig om de simulatie van haar databankversie te voorzien —
        dezelfde berekening, enkel op het punt waar de herkomst ervan nog
        beschikbaar is.
        """
        if basislijn is None:
            basislijn = self.bereken(van, tot)
        resultaat = scenario.voer_uit(
            self.dossier, conn=self.conn, settings=self.settings, van=van, tot=tot,
            basislijn=basislijn,
        )
        if not bewaar:
            return resultaat

        fout = self._bewaar_simulatie(scenario, resultaat, van, tot, data_version_id=basislijn.dataversie)
        if fout is not None:
            from dataclasses import replace

            resultaat = replace(resultaat, warnings=resultaat.warnings + (fout,))
        return resultaat

    def _bewaar_simulatie(
        self, scenario: "Scenario", resultaat: "ScenarioResultaat", van: date, tot: date,
        *, data_version_id: Optional[str],
    ) -> Optional[str]:
        """Schrijft `resultaat` weg naar `simulatie`, met genoeg herkomst
        (databankversie, code-commit, dossiersnapshot — zie
        `scenario.herkomst`) om het later exact te reproduceren en snel
        tegen andere gebruikers af te zetten.

        Geeft `None` terug bij succes, anders een waarschuwingstekst. Een
        opslagfout (bv. een databank zonder de nieuwste migratie) mag het al
        berekende scenarioresultaat niet ongeldig maken — maar ze mag ook niet
        stil verdwijnen, vandaar de teruggegeven waarschuwing in plaats van
        enkel een logregel.
        """
        from energie_vlaanderen.gebruikers.repository import GebruikersRepository
        from energie_vlaanderen.scenario import herkomst, opslag

        try:
            repo = GebruikersRepository(self.conn)
            repo.bewaar_gebruiker(self.dossier.gebruiker)
            snapshot = herkomst.dossier_snapshot(self.dossier)
            commit, dirty = herkomst.huidige_commit(self.settings.project_root)
            repo.bewaar_simulatie(
                gebruiker_id=self.dossier.gebruiker.id,
                scenario_type=type(scenario).__name__,
                scenario_naam=resultaat.naam,
                scenario_parameters=herkomst.scenario_parameters(scenario),
                periode_van=van,
                periode_tot=tot,
                dossier_hash=herkomst.dossier_hash(snapshot),
                dossier_snapshot=snapshot,
                resultaat=opslag.naar_dict(resultaat),
                exactheidsklasse=resultaat.exactheidsklasse,
                data_version_id=data_version_id,
                code_commit=commit,
                code_dirty=dirty,
                basislijn_totaal_eur=resultaat.totaal_basislijn,
                scenario_totaal_eur=resultaat.totaal_scenario,
                verschil_eur=resultaat.verschil_eur.get("totaal"),
                beste_leverancier=str(getattr(scenario, "leverancier", "")) or None,
                beste_product=str(getattr(scenario, "product", "")) or None,
                beste_contracttype=(
                    str(scenario.contracttype) if hasattr(scenario, "contracttype") else None
                ),
                aannames=resultaat.aannames,
                warnings=resultaat.warnings,
            )
            return None
        except Exception as exc:  # noqa: BLE001 - opslag mag de berekening nooit laten falen
            return f"Simulatie kon niet weggeschreven worden naar de databank: {exc}"


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
