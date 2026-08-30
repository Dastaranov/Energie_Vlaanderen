from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlalchemy


def _load_dotenv(project_root: Path) -> None:
    env_file = project_root / ".env"
    if not env_file.is_file():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file, override=False)
    except ImportError:
        pass


def get_dsn(project_root: Path | None = None) -> str:
    """Bouw de PostgreSQL DSN op uit omgevingsvariabelen (met .env als fallback)."""
    if project_root:
        _load_dotenv(project_root)

    host = os.environ.get("DB_HOST", "100.110.20.114")
    port = os.environ.get("DB_PORT", "5432")
    name = os.environ.get("DB_NAME", "energie_vlaanderen")
    user = os.environ.get("DB_USER", "endsor")
    password = os.environ.get("DB_PASSWORD", "")

    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"


def get_engine(project_root: Path | None = None) -> "sqlalchemy.Engine":
    """Geeft een SQLAlchemy Engine terug (voor Alembic en imports)."""
    import sqlalchemy as sa

    dsn = get_dsn(project_root)
    return sa.create_engine(dsn, pool_pre_ping=True)
