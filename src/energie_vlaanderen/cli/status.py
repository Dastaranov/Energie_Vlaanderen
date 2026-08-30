"""Dashboardgegevens voor de interactieve shell (opstart- en werkingsscherm).

Elke functie hier haalt één stukje status live op waar dat mogelijk is, en
geeft een eerlijke "nog niet geïmplementeerd"-tekst terug waar de codebase
de betreffende functionaliteit nog niet heeft (gebruikers, simulaties).
Geen enkele functie doet een netwerkoproep die de shell-opstart zou kunnen
vertragen of laten hangen.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

from energie_vlaanderen.audit.manager import ApprovalManager, AuditError
from energie_vlaanderen.data.paths import DataPaths, DataPathsError
from energie_vlaanderen.ingest.raw_store import RawStore
from energie_vlaanderen.settings import Settings

NIET_GEIMPLEMENTEERD = "nog niet geïmplementeerd"

DATABANK_NAAM = "energie_vlaanderen"
DATABANK_SERVER = "100.110.20.114"


def vandaag() -> str:
    return datetime.now().strftime("%d/%m/%Y")


def project_versie() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("energievergelijker-v3")
    except Exception:
        pass

    try:
        import tomllib

        pyproject = Settings.load().project_root / "pyproject.toml"
        with pyproject.open("rb") as fh:
            data = tomllib.load(fh)
        return data["project"]["version"]
    except Exception:
        return "onbekend"


def actieve_dataversie(paths: DataPaths) -> str:
    try:
        return paths.current_version()
    except DataPathsError:
        return "nog niet ingesteld"


def laatste_raw_run(paths: DataPaths) -> str:
    manifests = RawStore(paths).list_manifests()
    if not manifests:
        return "nog geen download uitgevoerd"
    laatste = max(manifests, key=lambda m: m.created_at)
    return laatste.created_at.strftime("%d/%m/%Y")


def geconfigureerde_links(settings: Settings) -> str:
    """Telt geconfigureerde bron-URLs — een config-check, geen live HTTP-oproep."""

    links = [settings.vtest_page_url, settings.tariff_page_url]
    aantal = sum(1 for link in links if link)
    return f"OK ({aantal} geconfigureerde link(en))"


def paths_status(paths: DataPaths) -> str:
    try:
        paths.ensure()
        return "OK"
    except DataPathsError:
        return "NOK"


def audit_status_voor_actieve_versie(paths: DataPaths) -> str:
    try:
        version_id = paths.current_version()
    except DataPathsError:
        return "onbekend (geen actieve versie)"

    try:
        status = ApprovalManager(paths).get_status(version_id)
        return status.status.upper()
    except AuditError:
        return "onbekend"


def api_key_status() -> str:
    key = os.environ.get("ENTSOE_API_KEY", "").strip()
    return "OK" if key else "NOK (ENTSOE_API_KEY ontbreekt)"


def db_verbinding() -> tuple[str, str]:
    """Geeft (verbindingsstatus, laatste_update) terug op basis van een live poging."""

    try:
        import sqlalchemy as sa

        from energie_vlaanderen.infrastructure.db.connection import get_engine
        from energie_vlaanderen.infrastructure.db.schema import data_version as dv_table
    except ImportError:
        return "niet beschikbaar (pip install .[db])", "onbekend"

    try:
        settings = Settings.load()
        engine = get_engine(settings.project_root)
        with engine.connect() as conn:
            row = conn.execute(
                sa.select(dv_table.c.geimporteerd_op)
                .where(dv_table.c.geimporteerd_op.is_not(None))
                .order_by(dv_table.c.geimporteerd_op.desc())
                .limit(1)
            ).first()
        laatste_update = row[0].strftime("%d/%m/%Y") if row and row[0] else "onbekend"
        return "actief", laatste_update
    except Exception:
        return "non-actief", "onbekend"


@dataclass
class DashboardData:
    datum: str
    databank: str
    server: str
    verbinding: str
    laatste_update: str
    versie_data: str
    versie_users: str
    tarieven_laatste_run: str
    tarieven_links: str
    tarieven_paths: str
    tarieven_tests: str
    tarieven_audit: str
    tarieven_versie: str
    api_keys: str
    gebruikers_aantal: str
    gebruikers_tests: str
    gebruikers_audit: str
    gebruikers_versie: str
    simulaties_tests: str
    simulaties_audit: str
    simulaties_versie: str


def collect(settings: Settings) -> DashboardData:
    paths = DataPaths.from_settings(settings)
    verbinding, laatste_update = db_verbinding()
    versie_data = actieve_dataversie(paths)

    return DashboardData(
        datum=vandaag(),
        databank=DATABANK_NAAM,
        server=DATABANK_SERVER,
        verbinding=verbinding,
        laatste_update=laatste_update,
        versie_data=versie_data,
        versie_users=NIET_GEIMPLEMENTEERD,
        tarieven_laatste_run=laatste_raw_run(paths),
        tarieven_links=geconfigureerde_links(settings),
        tarieven_paths=paths_status(paths),
        tarieven_tests="nog niet uitgevoerd",
        tarieven_audit=audit_status_voor_actieve_versie(paths),
        tarieven_versie=versie_data,
        api_keys=api_key_status(),
        gebruikers_aantal=NIET_GEIMPLEMENTEERD,
        gebruikers_tests=NIET_GEIMPLEMENTEERD,
        gebruikers_audit=NIET_GEIMPLEMENTEERD,
        gebruikers_versie=NIET_GEIMPLEMENTEERD,
        simulaties_tests=NIET_GEIMPLEMENTEERD,
        simulaties_audit=NIET_GEIMPLEMENTEERD,
        simulaties_versie=project_versie(),
    )
