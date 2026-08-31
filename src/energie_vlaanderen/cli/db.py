"""Databasecommando's: schema-init, import van gestagede versies, statusoverzicht."""

from __future__ import annotations

import argparse
import logging

from energie_vlaanderen.cli.helpers import fail
from energie_vlaanderen.cli.output import emit
from energie_vlaanderen.data.paths import DataPaths
from energie_vlaanderen.settings import Settings

LOG = logging.getLogger("energievergelijker")

_DB_IMPORT_ERROR = (
    "psycopg / SQLAlchemy / alembic niet geïnstalleerd. "
    "Voer 'pip install -e \".[db]\"' uit."
)


def _fail_missing_db_deps() -> int:
    LOG.error(_DB_IMPORT_ERROR)
    return 2


# ---------------------------------------------------------
# db-init
# ---------------------------------------------------------

def run_db_init(args: argparse.Namespace, settings: Settings) -> int:
    """Voer Alembic-migraties uit om het schema aan te maken of te upgraden."""
    try:
        from alembic import command as alembic_cmd
        from alembic.config import Config
    except ImportError:
        return _fail_missing_db_deps()

    alembic_ini = settings.project_root / "db" / "alembic.ini"
    if not alembic_ini.is_file():
        return fail("alembic.ini niet gevonden: %s", alembic_ini)

    from energie_vlaanderen.infrastructure.db.connection import get_dsn

    cfg = Config(str(alembic_ini))
    cfg.set_main_option("sqlalchemy.url", get_dsn(settings.project_root))

    LOG.info("Alembic-migraties uitvoeren tot 'head' ...")
    alembic_cmd.upgrade(cfg, "head")

    emit(
        args,
        text_fn=lambda: print("Schema is up-to-date."),
        json_obj={"status": "up-to-date"},
    )
    return 0


# ---------------------------------------------------------
# db-import
# ---------------------------------------------------------

def run_db_import(args: argparse.Namespace, settings: Settings) -> int:
    """Importeer een gestagede versie naar de databank."""
    try:
        import sqlalchemy as sa
        from sqlalchemy.dialects import postgresql  # noqa: F401 — triggert dialectregistratie

        from energie_vlaanderen.infrastructure.db import importer as imp
        from energie_vlaanderen.infrastructure.db.connection import get_engine
    except ImportError:
        return _fail_missing_db_deps()

    paths = DataPaths.from_settings(settings)
    version_id = args.version
    staging_dir = paths.staging / version_id

    if not staging_dir.is_dir():
        return fail("Staging-map niet gevonden: %s", staging_dir)

    engine = get_engine(settings.project_root)

    with engine.begin() as conn:
        from energie_vlaanderen.infrastructure.db.schema import data_version as dv_table

        existing = conn.execute(
            sa.select(dv_table.c.geimporteerd_op).where(dv_table.c.version_id == version_id)
        ).first()

        if existing and existing[0] is not None and not args.overwrite:
            return fail(
                "Versie %s is al geïmporteerd op %s. Gebruik --overwrite om te herladen.",
                version_id,
                existing[0].strftime("%Y-%m-%d %H:%M"),
            )

        if existing and args.overwrite:
            LOG.info("Bestaande rijen voor versie %s verwijderen ...", version_id)
            conn.execute(sa.text("DELETE FROM vtest_product WHERE version_id = :v"), {"v": version_id})
            conn.execute(sa.text("DELETE FROM vtest_scrape_run WHERE version_id = :v"), {"v": version_id})
            conn.execute(
                sa.text(
                    "DELETE FROM product_component WHERE leverancier_product_id IN "
                    "(SELECT id FROM leverancier_product WHERE version_id = :v)"
                ),
                {"v": version_id},
            )
            conn.execute(sa.text("DELETE FROM leverancier_product WHERE version_id = :v"), {"v": version_id})
            conn.execute(sa.text("DELETE FROM netwerk_tarief WHERE version_id = :v"), {"v": version_id})
            LOG.info("Bestaande rijen voor versie %s verwijderd.", version_id)

        imp.upsert_data_version(conn, version_id)

        results = []

        LOG.info("Netbeheerder-referentiedata zaaien ...")
        results.append(imp.seed_netbeheerder(conn))

        if args.gemeente:
            LOG.info("Importeren van DnbPerGemeente.csv ...")
            gemeente_csv = settings.data_root / "current" / "DnbPerGemeente.csv"
            if gemeente_csv.is_file():
                results.append(imp.import_gemeente(conn, gemeente_csv))
            else:
                LOG.warning("DnbPerGemeente.csv niet gevonden op %s", gemeente_csv)

        LOG.info("Importeren van vtest-producten ...")
        vtest_dir = staging_dir / "vtest"
        meta_json = vtest_dir / "vtest_dump_meta.json"
        vtest_csv = vtest_dir / "vtest_products.csv"
        if vtest_csv.is_file():
            scrape_run_id = imp.import_vtest_scrape_run(conn, version_id, meta_json, vtest_dir)
            results.append(imp.import_vtest_products(conn, version_id, vtest_csv, scrape_run_id=scrape_run_id))
        else:
            results.append(imp.import_vtest_products(conn, version_id, vtest_csv))

        LOG.info("Importeren van vtest-productkoppelingen (bulk-export) ...")
        results.append(
            imp.import_vtest_product_links(conn, version_id, vtest_dir / "vtest_product_links.csv")
        )

        LOG.info("Importeren van productcomponenten ...")
        results.append(
            imp.import_product_components(
                conn,
                vast_csv=vtest_dir / "master_vast.csv",
                var_dyn_csv=vtest_dir / "master_var_dyn.csv",
                version_id=version_id,
            )
        )

        LOG.info("Importeren van netwerktarieven ...")
        results.append(imp.import_netwerk_tarieven(conn, version_id, staging_dir / "tariffs"))

        imp.mark_imported(conn, version_id)

    def _text() -> None:
        for r in results:
            print(f"[{r.domain:<25}] {r.rows_inserted} rijen ingevoegd")
        print(f"Versie {version_id} geïmporteerd.")

    emit(
        args,
        text_fn=_text,
        json_obj={
            "version_id": version_id,
            "imported": [{"domain": r.domain, "rows_inserted": r.rows_inserted} for r in results],
        },
    )
    return 0


# ---------------------------------------------------------
# db-status
# ---------------------------------------------------------

def run_db_status(args: argparse.Namespace, settings: Settings) -> int:
    """Toon geïmporteerde versies en hun status."""
    try:
        import sqlalchemy as sa

        from energie_vlaanderen.infrastructure.db.connection import get_engine
        from energie_vlaanderen.infrastructure.db.schema import data_version as dv_table
    except ImportError:
        return _fail_missing_db_deps()

    engine = get_engine(settings.project_root)
    with engine.connect() as conn:
        rows = conn.execute(
            sa.select(
                dv_table.c.version_id,
                dv_table.c.status,
                dv_table.c.geimporteerd_op,
                dv_table.c.aangemaakt_op,
            ).order_by(dv_table.c.version_id.desc())
        ).fetchall()

    def _text() -> None:
        if not rows:
            print("Geen versies in de databank.")
            return
        for row in rows:
            imp_str = row[2].strftime("%Y-%m-%d %H:%M") if row[2] else "niet geïmporteerd"
            print(f"{row[0]}  {row[1]:<10}  {imp_str}")

    emit(
        args,
        text_fn=_text,
        json_obj=[
            {
                "version_id": row[0],
                "status": row[1],
                "geimporteerd_op": row[2].isoformat() if row[2] else None,
                "aangemaakt_op": row[3].isoformat() if row[3] else None,
            }
            for row in rows
        ],
    )
    return 0

