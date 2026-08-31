"""Tests voor infrastructure/db/importer.py — netbeheerder code/naam-koppeling.

De pure-Python logica (_dnb_code) wordt als gewone unit-test gedraaid. Tests
die effectief tegen de Postgres-databank draaien (seed_netbeheerder,
import_gemeente) zijn gemarkeerd als integration en slaan zichzelf snel over
(korte connect_timeout, zie cli/status.py::db_verbinding) wanneer er geen
Tailscale-toegang is — consistent met `pytest -m "not integration"`.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from energie_vlaanderen.infrastructure.db.importer import (
    _dnb_code,
    import_gemeente,
    import_netwerk_tarieven,
    seed_netbeheerder,
)
from energie_vlaanderen.utility.constants import DNB_CODES

DB_CONNECT_TIMEOUT_SECONDS = 2


class TestDnbCode:
    """Pure-Python: geen databankverbinding nodig."""

    def test_dnb_code_maps_known_fluvius_names(self):
        for naam, code in DNB_CODES.items():
            assert _dnb_code(naam) == code

    def test_dnb_code_falls_back_for_unknown_name_and_warns(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = _dnb_code("Enexis Netbeheer")

        assert result == "Enexis Netbeheer"
        assert any(
            "Enexis Netbeheer" in record.message
            for record in caplog.records
        )


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


@pytest.mark.integration
class TestSeedNetbeheerder:
    def test_seed_netbeheerder_is_idempotent(self, db_conn):
        import sqlalchemy as sa

        from energie_vlaanderen.infrastructure.db.schema import netbeheerder

        seed_netbeheerder(db_conn)
        seed_netbeheerder(db_conn)

        rows = db_conn.execute(
            sa.select(netbeheerder.c.code).where(
                netbeheerder.c.code.in_(list(DNB_CODES.values()))
            )
        ).all()
        assert len(rows) == len(DNB_CODES)


@pytest.mark.integration
class TestImportGemeente:
    def test_import_gemeente_sets_abbreviation_as_code_and_full_name_as_naam(
        self, db_conn, tmp_path
    ):
        import sqlalchemy as sa

        from energie_vlaanderen.infrastructure.db.schema import gemeente, netbeheerder

        csv_path = tmp_path / "DnbPerGemeente.csv"
        csv_path.write_text(
            "Postcode;Gemeente;DNB Elektriciteit;DNB Gas;GasType Oud;GasType Nieuw\n"
            "2000;Antwerpen;Fluvius Antwerpen;Fluvius Antwerpen;A;A\n"
            "3500;Hasselt;Fluvius Limburg;Enexis Netbeheer;A;A\n",
            encoding="utf-8-sig",
        )

        import_gemeente(db_conn, csv_path)

        nb_rows = {
            row.code: row.naam
            for row in db_conn.execute(
                sa.select(netbeheerder.c.code, netbeheerder.c.naam)
            ).all()
        }
        assert nb_rows.get("FA") == "Fluvius Antwerpen"
        assert nb_rows.get("Enexis Netbeheer") == "Enexis Netbeheer"

        gem_rows = {
            row.postcode: (row.dnb_elektriciteit, row.dnb_gas)
            for row in db_conn.execute(
                sa.select(
                    gemeente.c.postcode,
                    gemeente.c.dnb_elektriciteit,
                    gemeente.c.dnb_gas,
                )
            ).all()
        }
        assert gem_rows["2000"] == ("FA", "FA")
        assert gem_rows["3500"] == ("FL", "Enexis Netbeheer")


@pytest.mark.integration
class TestImportNetwerkTarieven:
    """De hoogspanning-CSV bevat gemengde Afname/Injectie-rijen (geen vaste
    richting per bestand) — dit test dat contract_richting per rij correct
    wordt afgeleid uit de Contracttype-kolom."""

    VERSION_ID = "20260821T160221Z-ff1992b3"

    def _seed_data_version(self, db_conn) -> None:
        import sqlalchemy as sa

        from energie_vlaanderen.infrastructure.db.schema import data_version

        db_conn.execute(
            sa.dialects.postgresql.insert(data_version)
            .values(version_id=self.VERSION_ID, aangemaakt_op=sa.func.now())
            .on_conflict_do_nothing(index_elements=["version_id"])
        )

    def test_hoogspanning_csv_derives_richting_per_row(self, db_conn, tmp_path):
        import sqlalchemy as sa

        from energie_vlaanderen.infrastructure.db.schema import netwerk_tarief

        self._seed_data_version(db_conn)
        seed_netbeheerder(db_conn)

        header = "Netbeheerder;Contracttype;Tarieftype;Tariefdetail;source_sheet;source_row;Tariefnotering;Klanttype;Prijs_num\n"
        (tmp_path / "tariffs_electricity_hoogspanning.csv").write_text(
            header
            + "FA;Afname;Netgebruik;Toegangsvermogen;FA ELEK Afname;6;EUR/kVA/maand;ELEK_HS1;3.470105\n"
            + "FA;Injectie;Tarief databeheer;26-36 kV, 1-26 kV, distributiecabine;FA ELEK Injectie;7;EUR/jaar;ELEK_HS1;57.65\n",
            encoding="utf-8-sig",
        )
        # De overige 4 bestanden ontbreken bewust — import_netwerk_tarieven
        # moet ontbrekende bestanden overslaan (bestaand gedrag).

        import_netwerk_tarieven(db_conn, self.VERSION_ID, tmp_path)

        rows = db_conn.execute(
            sa.select(netwerk_tarief.c.contract_richting, netwerk_tarief.c.klanttype)
            .where(netwerk_tarief.c.version_id == self.VERSION_ID)
            .order_by(netwerk_tarief.c.contract_richting)
        ).all()

        assert {(r.contract_richting, r.klanttype) for r in rows} == {
            ("afname", "ELEK_HS1"),
            ("injectie", "ELEK_HS1"),
        }
