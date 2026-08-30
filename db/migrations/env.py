from __future__ import annotations

import sys
from pathlib import Path

# Voeg src/ toe aan het pad zodat energie_vlaanderen importeerbaar is
_repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_repo_root / "src"))

from alembic import context
from energie_vlaanderen.infrastructure.db.connection import get_dsn
from energie_vlaanderen.infrastructure.db.schema import metadata

config = context.config

# Laad DSN uit omgevingsvariabelen + .env
dsn = get_dsn(project_root=_repo_root)
config.set_main_option("sqlalchemy.url", dsn)

target_metadata = metadata


def run_migrations_offline() -> None:
    context.configure(
        url=dsn,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import engine_from_config, pool
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
