"""Databasecommando's: schema-init, import van gestagede versies, statusoverzicht."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

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

def import_version_into_db(
    *,
    settings: Settings,
    version_id: str,
    bron_dir: Path,
    overwrite: bool = False,
    gemeente: bool = True,
) -> list:
    """Importeer één dataversie uit `bron_dir` naar de databank.

    `bron_dir` is de map met de verwerkte CSV's — `versions/<id>/` voor een
    gepubliceerde versie, `staging/<id>/` voor een die nog in verwerking is.
    Voorheen kon dit enkel uit staging, terwijl `version publish` staging
    opruimt: publiceren maakte een versie daarmee onimporteerbaar.

    Deze functie zit los van de CLI zodat `version publish` ze kan aanroepen
    en publiceren en importeren één handeling worden.

    Importvolgorde (na 0007-migratie):
    1. Referentiedata: netbeheerder, gemeente
    2. Leverancier/product-data uit CSV
    3. vtest-contracten en postcode-prijzen
    4. Netbeheerder-tarieven (SCD2)
    5. Overheidsheffingen

    Met `overwrite` wordt alleen version_id-gebonden data verwijderd
    (vtest_scrape_run, vtest_postcode_prijs). De tariefhistoriek blijft
    intact: netbeheerder_tarief en tarief_afname/injectie zijn SCD2 en niet
    aan een version_id gebonden.
    """
    import sqlalchemy as sa
    from sqlalchemy.dialects import postgresql  # noqa: F401 — dialectregistratie

    from energie_vlaanderen.infrastructure.db import importer as imp
    from energie_vlaanderen.infrastructure.db.connection import get_engine
    from energie_vlaanderen.infrastructure.db.schema import data_version as dv_table

    if not bron_dir.is_dir():
        raise FileNotFoundError(f"Bronmap voor de import niet gevonden: {bron_dir}")

    engine = get_engine(settings.project_root)
    results = []

    with engine.begin() as conn:
        bestaand = conn.execute(
            sa.select(dv_table.c.geimporteerd_op).where(
                dv_table.c.version_id == version_id
            )
        ).first()

        if bestaand and bestaand[0] is not None and not overwrite:
            raise ValueError(
                f"Versie {version_id} is al geïmporteerd op "
                f"{bestaand[0].strftime('%Y-%m-%d %H:%M')}. "
                "Gebruik --overwrite om te herladen."
            )

        if bestaand and overwrite:
            LOG.info("Bestaande version_id-gebonden rijen voor %s verwijderen ...", version_id)
            LOG.info("  (Tariefhistoriek (SCD2) blijft intact)")
            conn.execute(
                sa.text("DELETE FROM vtest_postcode_prijs WHERE version_id = :v"),
                {"v": version_id},
            )
            conn.execute(
                sa.text("DELETE FROM vtest_scrape_run WHERE version_id = :v"),
                {"v": version_id},
            )

        imp.upsert_data_version(conn, version_id)

        LOG.info("Netbeheerder-referentiedata zaaien ...")
        results.append(imp.seed_netbeheerder(conn))

        if gemeente:
            LOG.info("Importeren van DnbPerGemeente.csv ...")
            gemeente_csv = settings.data_root / "current" / "DnbPerGemeente.csv"
            if gemeente_csv.is_file():
                results.append(imp.import_gemeente(conn, gemeente_csv))
            else:
                LOG.warning("DnbPerGemeente.csv niet gevonden op %s", gemeente_csv)

        LOG.info("Importeren van leverancier/product-data ...")
        vtest_dir = bron_dir / "vtest"
        results.append(
            imp.import_leverancier_en_product(
                conn,
                vast_csv=vtest_dir / "master_vast.csv",
                var_dyn_csv=vtest_dir / "master_var_dyn.csv",
            )
        )

        LOG.info("Koppelen van vreg_id's via product matcher ...")
        results.append(
            imp.link_energie_product_vreg_ids(
                conn,
                vast_csv=vtest_dir / "master_vast.csv",
                var_dyn_csv=vtest_dir / "master_var_dyn.csv",
                links_csv=vtest_dir / "vtest_product_links.csv",
            )
        )

        LOG.info("Aanvullen van producteigenschappen uit de scrape ...")
        results.append(
            imp.import_energie_product_kenmerken(
                conn, vtest_dir / "vtest_products.csv"
            )
        )

        LOG.info("Importeren van vtest-scrape-metadata en contract-prijzen ...")
        meta_json = vtest_dir / "vtest_dump_meta.json"
        vtest_csv = vtest_dir / "vtest_products.csv"
        if vtest_csv.is_file():
            imp.import_vtest_scrape_run(conn, version_id, meta_json, vtest_dir)
            results.append(imp.import_vtest_contract_en_prijzen(conn, version_id, vtest_csv))
        else:
            LOG.warning("vtest_products.csv niet gevonden, overgeslagen")

        LOG.info("Importeren van netbeheerder-tarieven (SCD2) ...")
        jaar = int(version_id[:4])
        results.append(imp.import_netbeheerder_tarieven(conn, bron_dir / "tariffs", jaar))

        LOG.info("Importeren van vervoerstarieven ...")
        results.append(
            imp.import_nettarief_transport(
                conn, settings.project_root / "config" / "nettarieven"
            )
        )

        LOG.info("Importeren van overheidsheffingen ...")
        results.append(
            # config/heffingen/, niet config/: HeffingenRepository.load zoekt
            # daar de bijzondere_accijns_*.toml. Deze verkeerde map bleef
            # jarenlang onopgemerkt omdat de importer elke fout wegving en
            # daarna succes meldde — de databank kreeg dus nooit heffingen.
            imp.import_overheidsheffingen(
                conn, settings.project_root / "config" / "heffingen"
            )
        )

        imp.mark_imported(conn, version_id)

    return results


def mark_version_active_in_db(settings: Settings, version_id: str) -> None:
    """Zet `geactiveerd_op` op deze versie en haal het bij alle andere weg.

    Zo zegt de databank hetzelfde als `current.txt`: precies één actieve
    versie, en `db verify` kan de twee tegen elkaar leggen.
    """
    import sqlalchemy as sa

    from energie_vlaanderen.infrastructure.db.connection import get_engine
    from energie_vlaanderen.infrastructure.db.schema import data_version as dv_table

    engine = get_engine(settings.project_root)
    with engine.begin() as conn:
        conn.execute(
            sa.update(dv_table)
            .where(dv_table.c.version_id != version_id)
            .values(geactiveerd_op=None)
        )
        conn.execute(
            sa.update(dv_table)
            .where(dv_table.c.version_id == version_id)
            .values(geactiveerd_op=sa.func.now(), status="active")
        )


def run_db_import(args: argparse.Namespace, settings: Settings) -> int:
    """Importeer een dataversie naar de databank.

    Zoekt de versie eerst in `versions/` (gepubliceerd) en anders in
    `staging/`. Zo werkt het commando zowel vóór als na publicatie.
    """
    try:
        import sqlalchemy  # noqa: F401
    except ImportError:
        return _fail_missing_db_deps()

    paths = DataPaths.from_settings(settings)
    version_id = args.version

    version_dir = paths.versions / version_id
    staging_dir = paths.staging / version_id
    if version_dir.is_dir():
        bron_dir, herkomst = version_dir, "versions"
    elif staging_dir.is_dir():
        bron_dir, herkomst = staging_dir, "staging"
    else:
        return fail(
            "Versie %s niet gevonden in versions/ noch in staging/.", version_id
        )

    LOG.info("Bron voor de import: %s (%s)", bron_dir, herkomst)

    try:
        results = import_version_into_db(
            settings=settings,
            version_id=version_id,
            bron_dir=bron_dir,
            overwrite=args.overwrite,
            gemeente=args.gemeente,
        )
    except (FileNotFoundError, ValueError) as exc:
        return fail("%s", exc)
    except Exception as exc:
        # Een databankfout is een verwachte uitkomst van dit commando, geen
        # bug: de transactie is teruggedraaid, dus de databank staat nog zoals
        # ze stond. Een leesbare melding is bruikbaarder dan een traceback.
        return fail(
            "Import van versie %s mislukt en volledig teruggedraaid: %s",
            version_id, exc,
        )

    def _text() -> None:
        for r in results:
            print(f"[{r.domain:<25}] {r.rows_inserted} rijen ingevoegd")
        print(f"Versie {version_id} geïmporteerd vanuit {herkomst}.")

    emit(
        args,
        text_fn=_text,
        json_obj={
            "version_id": version_id,
            "source": herkomst,
            "source_dir": str(bron_dir),
            "imported": [
                {"domain": r.domain, "rows_inserted": r.rows_inserted} for r in results
            ],
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



# ---------------------------------------------------------
# db-verify
# ---------------------------------------------------------

def run_db_verify(args: argparse.Namespace, settings: Settings) -> int:
    """Toets of de databank één op één overeenkomt met current.txt.

    De databank is het eindstation: wat `current.txt` de actieve versie noemt,
    hoort in de databank te staan, geïmporteerd te zijn en daar ook als actief
    gemarkeerd te staan. Zolang die drie niet toetsbaar zijn, is "1 op 1" een
    aanname in plaats van een eigenschap.

    Exitcode 0 als alles klopt, 2 bij een verschil.
    """
    try:
        import sqlalchemy as sa

        from energie_vlaanderen.infrastructure.db.connection import get_engine
        from energie_vlaanderen.infrastructure.db.schema import (
            data_version as dv_table,
            metadata,
        )
    except ImportError:
        return _fail_missing_db_deps()

    paths = DataPaths.from_settings(settings)
    bevindingen: list[str] = []

    huidige = paths.current_version()
    if huidige is None:
        bevindingen.append(
            "current.txt wijst naar geen enkele versie; er is geen actieve dataset."
        )

    try:
        engine = get_engine(settings.project_root)
        with engine.connect() as conn:
            aanwezige_tabellen = set(sa.inspect(engine).get_table_names())
            ontbrekende_tabellen = sorted(
                {t.name for t in metadata.sorted_tables} - aanwezige_tabellen
            )

            rijen = conn.execute(
                sa.select(
                    dv_table.c.version_id,
                    dv_table.c.status,
                    dv_table.c.geimporteerd_op,
                    dv_table.c.geactiveerd_op,
                )
            ).fetchall()
    except Exception as exc:
        return fail("Databank niet bereikbaar: %s", exc)

    per_versie = {r.version_id: r for r in rijen}
    actief_in_db = [r.version_id for r in rijen if r.geactiveerd_op is not None]

    if ontbrekende_tabellen:
        bevindingen.append(
            f"{len(ontbrekende_tabellen)} tabel(len) uit het schema ontbreken in "
            f"de databank: {', '.join(ontbrekende_tabellen)}. "
            "Draai `energievergelijker db init` (alembic upgrade head)."
        )

    if huidige is not None:
        rij = per_versie.get(huidige)
        if rij is None:
            bevindingen.append(
                f"Actieve versie {huidige} uit current.txt staat niet in de databank. "
                f"Draai `energievergelijker db import --version {huidige}`."
            )
        else:
            if rij.geimporteerd_op is None:
                bevindingen.append(
                    f"Versie {huidige} staat in de databank maar is nooit "
                    "volledig geïmporteerd (geimporteerd_op is leeg)."
                )
            if rij.geactiveerd_op is None:
                bevindingen.append(
                    f"Versie {huidige} is niet als actief gemarkeerd in de databank."
                )

    if len(actief_in_db) > 1:
        bevindingen.append(
            "Meer dan één versie staat als actief in de databank: "
            f"{', '.join(sorted(actief_in_db))}. Er hoort er precies één te zijn."
        )
    for version_id in actief_in_db:
        if huidige is not None and version_id != huidige:
            bevindingen.append(
                f"De databank noemt {version_id} actief, current.txt noemt {huidige}."
            )

    def _text() -> None:
        print(f"current.txt        : {huidige or '(geen)'}")
        print(f"Actief in databank : {', '.join(actief_in_db) or '(geen)'}")
        print(f"Versies in databank: {len(per_versie)}")
        for version_id, rij in sorted(per_versie.items()):
            merk = "*" if rij.geactiveerd_op is not None else " "
            geimporteerd = (
                rij.geimporteerd_op.strftime("%Y-%m-%d %H:%M")
                if rij.geimporteerd_op
                else "niet geïmporteerd"
            )
            print(f"  {merk} {version_id}  {rij.status:<10} {geimporteerd}")
        print()
        if bevindingen:
            for bevinding in bevindingen:
                print(f"[VERSCHIL] {bevinding}")
        else:
            print("Databank en current.txt komen één op één overeen.")

    emit(
        args,
        text_fn=_text,
        json_obj={
            "current_txt": huidige,
            "actief_in_databank": actief_in_db,
            "versies": [
                {
                    "version_id": version_id,
                    "status": rij.status,
                    "geimporteerd_op": (
                        rij.geimporteerd_op.isoformat() if rij.geimporteerd_op else None
                    ),
                    "geactiveerd_op": (
                        rij.geactiveerd_op.isoformat() if rij.geactiveerd_op else None
                    ),
                }
                for version_id, rij in sorted(per_versie.items())
            ],
            "verschillen": bevindingen,
        },
    )
    return 2 if bevindingen else 0
