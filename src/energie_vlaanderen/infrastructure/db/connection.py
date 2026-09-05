"""
Database connection via SQLAlchemy.
Database structure is defined in `energie_vlaanderen.infrastructure.db.schema`.
The database connection parameters are read from environment variables, 
with a fallback to a `.env` file in the project root if provided.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlalchemy

"""
Functions to get a SQLAlchemy Engine and DSN from environment variables.
args: 
    project_root: Path | None = None
        The root of the project, used to locate a .env file for environment variables.
        If None, only the current environment variables are used.
Returns:
    sqlalchemy.Engine: A SQLAlchemy Engine object for connecting to the database.
"""
def _load_dotenv(project_root: Path) -> None:
    env_file = project_root / ".env"
    if not env_file.is_file():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file, override=False)
    except ImportError:
        pass

"""
Functions to get a SQLAlchemy Engine and DSN from environment variables.
args:
    project_root: Path | None = None
        The root of the project, used to locate a .env file for environment variables.
        If None, only the current environment variables are used.
Returns:
    str: A PostgreSQL DSN string for connecting to the database.
"""
def get_dsn(project_root: Path | None = None) -> str:
    """Bouw de PostgreSQL DSN op uit omgevingsvariabelen (met .env als fallback)."""
    import sqlalchemy as sa

    if project_root:
        _load_dotenv(project_root)

    host = os.environ.get("DB_HOST", "100.110.20.114")
    port = os.environ.get("DB_PORT", "5432")
    name = os.environ.get("DB_NAME", "energie_vlaanderen")
    user = os.environ.get("DB_USER", "endsor")
    password = os.environ.get("DB_PASSWORD", "")

    # Via `URL.create` en niet via een f-string: een wachtwoord met @, :, /, ?,
    # # of % breekt anders de URL of wordt verkeerd geparsed -- @ splitst
    # gebruiker van host, % start een percent-escape. Dat geeft geen foutmelding
    # over het wachtwoord maar een onbegrijpelijke verbindingsfout.
    #
    # `render_as_string` codeert wat gecodeerd moet worden; `make_url()` aan de
    # andere kant (dump.py leest er host, gebruiker en wachtwoord uit voor psql)
    # decodeert het weer.
    return sa.engine.URL.create(
        "postgresql+psycopg",
        username=user,
        password=password or None,
        host=host,
        port=int(port),
        database=name,
    ).render_as_string(hide_password=False)


def get_engine(project_root: Path | None = None) -> "sqlalchemy.Engine":
    """Geeft een SQLAlchemy Engine terug (voor Alembic en imports)."""
    import sqlalchemy as sa

    dsn = get_dsn(project_root)
    return sa.create_engine(dsn, pool_pre_ping=True)
