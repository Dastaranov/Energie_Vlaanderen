from __future__ import annotations

import os
from pathlib import Path

import pytest


REQUIRED_DATA_FILES = (
    Path("vtest") / "master_vast.csv",
    Path("vtest") / "master_var_dyn.csv",
)


def has_required_data(path: Path) -> bool:
    return path.is_dir() and all(
        (path / rel_path).is_file()
        for rel_path in REQUIRED_DATA_FILES
    )


@pytest.fixture(scope="session")
def project_root() -> Path:
    root = Path(__file__).resolve().parents[1]

    if not (root / "pyproject.toml").is_file():
        pytest.fail(
            f"Projectroot lijkt ongeldig: {root}. "
            "pyproject.toml werd niet gevonden."
        )

    return root


@pytest.fixture(scope="session")
def data_root(project_root: Path) -> Path:
    candidates: list[Path] = []

    configured = os.getenv("ENERGIEVERGELIJKER_DATA_DIR")
    if configured:
        candidates.append(
            Path(configured).expanduser().resolve()
        )

    current_pointer = project_root / "data" / "current.txt"

    if current_pointer.is_file():
        version = current_pointer.read_text(
            encoding="utf-8"
        ).strip()

        if version:
            candidates.append(
                project_root / "data" / "versions" / version
            )

    candidates.extend(
        [
            project_root / "data" / "current",
            project_root / "data",
            project_root,
        ]
    )

    for candidate in candidates:
        if has_required_data(candidate):
            return candidate

    checked = "\n".join(
        f"  - {candidate}"
        for candidate in candidates
    )

    pytest.skip(
        "Geen volledige integratiedataset gevonden.\n"
        f"Gecontroleerde locaties:\n{checked}\n"
        "Stel ENERGIEVERGELIJKER_DATA_DIR in om "
        "integratietests uit te voeren."
    )


# Twee seconden: de databank hangt aan een Tailscale-adres. Is dat er niet,
# dan moet de suite dat snel vaststellen en overslaan in plaats van per test
# op een TCP-timeout te wachten.
DB_CONNECT_TIMEOUT_SECONDS = 2


@pytest.fixture()
def db_conn():
    """Levert een transactionele DB-connectie; slaat de test over zonder
    (snel) bereikbare Tailscale-databank. Alle wijzigingen worden aan het
    einde teruggerold — geen blijvende effecten op de echte databank."""
    import sqlalchemy as sa

    from energie_vlaanderen.infrastructure.db.connection import get_dsn

    project_root = Path(__file__).resolve().parents[1]
    dsn = get_dsn(project_root)
    engine = sa.create_engine(
        dsn,
        pool_pre_ping=True,
        connect_args={"connect_timeout": DB_CONNECT_TIMEOUT_SECONDS},
    )

    try:
        conn = engine.connect()
    except Exception as exc:
        pytest.skip(f"Geen bereikbare databank: {exc}")

    trans = conn.begin()
    try:
        yield conn
    finally:
        trans.rollback()
        conn.close()
        engine.dispose()
