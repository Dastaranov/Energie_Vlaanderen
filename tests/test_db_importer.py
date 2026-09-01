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
    _map_component_code_to_field,
    import_gemeente,
    import_netbeheerder_tarieven,
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
        """Een netbeheerder die we niet kennen gaat als volledige naam door.

        Het voorbeeld was hier "Enexis Netbeheer" — de gasnetbeheerder van
        Baarle-Hertog. Die is inmiddels wél bekend (met code ENEXIS, zonder
        tarieven), dus dit toetst nu een naam die echt nergens voorkomt.
        """
        with caplog.at_level(logging.WARNING):
            result = _dnb_code("Netbeheerder Die Niet Bestaat")

        assert result == "Netbeheerder Die Niet Bestaat"
        assert any(
            "Netbeheerder Die Niet Bestaat" in record.message
            for record in caplog.records
        )

    def test_enexis_krijgt_zijn_eigen_code(self):
        """Baarle-Hertog krijgt zijn aardgas van Enexis; die hoort herkend te
        worden in plaats van als losse naam de databank in te gaan."""
        assert _dnb_code("Enexis Netbeheer") == "ENEXIS"


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
        # Enexis levert het aardgas van Baarle-Hertog en heeft sinds kort een
        # eigen code, zodat de naam niet als code de databank in gaat.
        assert nb_rows.get("ENEXIS") == "Enexis Netbeheer"

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
        assert gem_rows["3500"] == ("FL", "ENEXIS")


class TestMapComponentCodeToField:
    """Pure-Python: Component-code mapping tests."""

    def test_maps_energieprijs_variants(self):
        assert _map_component_code_to_field("energieprijs") == "energieprijs_kwh"
        assert _map_component_code_to_field("energy_price") == "energieprijs_kwh"
        assert _map_component_code_to_field("ENERGIEPRIJS_KWH") == "energieprijs_kwh"

    def test_maps_surcharge_components(self):
        assert _map_component_code_to_field("groene stroom") == "groene_stroom_kwh"
        assert _map_component_code_to_field("green") == "groene_stroom_kwh"
        assert _map_component_code_to_field("wkk") == "wkk_kwh"
        assert _map_component_code_to_field("bijdrage op de energie") == "energiebijdrage_kwh"

    def test_maps_vaste_vergoeding(self):
        assert _map_component_code_to_field("vaste vergoeding") == "vaste_vergoeding_jaar"
        assert _map_component_code_to_field("fixed_fee") == "vaste_vergoeding_jaar"

    def test_maps_parameters(self):
        for param in ("a", "b", "c", "d", "z"):
            assert _map_component_code_to_field(f"param_{param}") == f"param_{param}"

    def test_maps_indices(self):
        for idx in ("a", "b", "c", "d"):
            assert _map_component_code_to_field(f"index_name_{idx}") == f"index_naam_{idx}"
            assert _map_component_code_to_field(f"index_value_{idx}") == f"index_waarde_{idx}"

    def test_returns_none_for_unknown_code(self):
        assert _map_component_code_to_field("unknown_component") is None
        assert _map_component_code_to_field("") is None
        assert _map_component_code_to_field(None) is None

    def test_returns_none_for_meter_types(self):
        # Meter-type codes shouldn't map to tariff columns
        # (they're handled separately as meter_type values)
        for meter_type in ("single", "day", "night", "exclusive_night"):
            # These should return None because they're not tariff-value components
            result = _map_component_code_to_field(meter_type)
            assert result is None, f"meter_type '{meter_type}' should not map to a tariff column"


@pytest.mark.integration
class TestImportNetbeheerderTarieven:
    """De hoogspanning-CSV bevat gemengde Afname/Injectie-rijen (geen vaste
    richting per bestand) — dit test dat contract_richting per rij correct
    wordt afgeleid uit de Contracttype-kolom. SCD2: geen version_id, maar geldig_van/tot."""

    def test_hoogspanning_csv_derives_richting_per_row_scd2(self, db_conn, tmp_path):
        import sqlalchemy as sa

        from energie_vlaanderen.infrastructure.db.schema import netbeheerder_tarief

        seed_netbeheerder(db_conn)

        header = "Netbeheerder;Contracttype;Tarieftype;Tariefdetail;source_sheet;source_row;Tariefnotering;Klanttype;Prijs_num\n"
        (tmp_path / "tariffs_electricity_hoogspanning.csv").write_text(
            header
            + "FA;Afname;Netgebruik;Toegangsvermogen;FA ELEK Afname;6;EUR/kVA/maand;ELEK_HS1;3.470105\n"
            + "FA;Injectie;Tarief databeheer;26-36 kV, 1-26 kV, distributiecabine;FA ELEK Injectie;7;EUR/jaar;ELEK_HS1;57.65\n",
            encoding="utf-8-sig",
        )

        import_netbeheerder_tarieven(db_conn, tmp_path, jaar=2026)

        # Filter op de eigen bronbladen: deze test deelt de tabel met de
        # echte tariefdata, en die bevat honderden open rijen. Zonder filter
        # slaagde de test alleen zolang de databank leeg was.
        rows = db_conn.execute(
            sa.select(netbeheerder_tarief.c.contract_richting, netbeheerder_tarief.c.klanttype)
            .where(
                netbeheerder_tarief.c.geldig_tot.is_(None)
                & netbeheerder_tarief.c.source_sheet.in_(
                    ["FA ELEK Afname", "FA ELEK Injectie"]
                )
                & (netbeheerder_tarief.c.tarieftype == "Netgebruik")
                | (
                    netbeheerder_tarief.c.geldig_tot.is_(None)
                    & (netbeheerder_tarief.c.tarieftype == "Tarief databeheer")
                    & (netbeheerder_tarief.c.klanttype == "ELEK_HS1")
                )
            )
            .order_by(netbeheerder_tarief.c.contract_richting)
        ).all()

        assert {(r.contract_richting, r.klanttype) for r in rows} == {
            ("afname", "ELEK_HS1"),
            ("injectie", "ELEK_HS1"),
        }

    def test_scd2_closes_old_row_on_new_import(self, db_conn, tmp_path):
        """SCD2-test: tweede import sluit oude open rij en voegt nieuwe toe."""
        import sqlalchemy as sa
        from datetime import date

        from energie_vlaanderen.infrastructure.db.schema import netbeheerder_tarief

        seed_netbeheerder(db_conn)

        # Eerste import
        header = "Netbeheerder;Contracttype;Tarieftype;Tariefdetail;source_sheet;source_row;Tariefnotering;Klanttype;Prijs_num\n"
        (tmp_path / "tariffs_electricity_afname.csv").write_text(
            header + "FA;Afname;Netgebruik;Laagspanning;FA ELEK LS;1;ct/kWh;ELEK_LV1;15.50\n",
            encoding="utf-8-sig",
        )

        import_netbeheerder_tarieven(db_conn, tmp_path, jaar=2026)

        # Controleer open rij
        # Filter op het klanttype van deze test: ELEK_LV1 bestaat niet in de
        # echte tariefdata, waarmee de test onafhankelijk wordt van wat er al
        # in de gedeelde databank staat.
        row1 = db_conn.execute(
            sa.select(netbeheerder_tarief.c.id, netbeheerder_tarief.c.geldig_tot)
            .where(
                (netbeheerder_tarief.c.netbeheerder_code == "FA")
                & (netbeheerder_tarief.c.klanttype == "ELEK_LV1")
                & (netbeheerder_tarief.c.geldig_tot.is_(None))
            )
        ).fetchone()
        assert row1 is not None
        row1_id = row1[0]

        # Tweede import (volgende jaar = nieuwe geldig_van)
        import_netbeheerder_tarieven(db_conn, tmp_path, jaar=2027)

        # Oude rij moet gesloten zijn
        old_row = db_conn.execute(
            sa.select(netbeheerder_tarief.c.id, netbeheerder_tarief.c.geldig_tot)
            .where(netbeheerder_tarief.c.id == row1_id)
        ).fetchone()
        assert old_row is not None
        assert old_row[1] == date(2026, 12, 31), "Old row should be closed with geldig_tot = last day of 2026"

        # Nieuwe open rij moet bestaan
        new_row = db_conn.execute(
            sa.select(netbeheerder_tarief.c.id, netbeheerder_tarief.c.geldig_tot)
            .where(
                (netbeheerder_tarief.c.netbeheerder_code == "FA")
                & (netbeheerder_tarief.c.geldig_tot.is_(None))
            )
        ).fetchone()
        assert new_row is not None
        assert new_row[0] != row1_id, "New row should be different from old row"


@pytest.mark.integration
class TestImportVtestPostcodePrijs:
    """Regressietest voor bug #1: alle 8 postcodes moeten ingevoegd worden."""

    VERSION_ID = "20260829T202059Z-853a7046"

    def _seed_data_version(self, db_conn) -> None:
        import sqlalchemy as sa

        from energie_vlaanderen.infrastructure.db.schema import data_version

        db_conn.execute(
            sa.dialects.postgresql.insert(data_version)
            .values(version_id=self.VERSION_ID, aangemaakt_op=sa.func.now())
            .on_conflict_do_nothing(index_elements=["version_id"])
        )

    def test_vtest_postcode_prijs_no_silent_loss(self, db_conn, tmp_path):
        """Bug #1 fix: ON CONFLICT DO NOTHING mag NIET non-deterministisch
        postcodes weggooien. Dit test dat alle rijen ingevoegd worden."""
        import sqlalchemy as sa

        from energie_vlaanderen.infrastructure.db.schema import (
            vtest_contract,
            vtest_postcode_prijs,
            leverancier,
        )
        from energie_vlaanderen.infrastructure.db.importer import import_vtest_contract_en_prijzen

        self._seed_data_version(db_conn)

        # Seed een dummy-leverancier voor FK
        db_conn.execute(
            sa.dialects.postgresql.insert(leverancier)
            .values(naam="Test Leverancier")
            .on_conflict_do_nothing(index_elements=["naam"])
        )

        # Maak een vtest_products.csv met 8 verschillende postcodes
        csv_path = tmp_path / "vtest_products.csv"
        header = "vreg_id;supplier_raw;product_raw;energy;tariff_type;postcode;segment;total_excl_btw;total_incl_btw;btw_bedrag;totaal_verbruik_kwh;scraped_at\n"
        lines = [header]
        for i, pc in enumerate(["9000", "9001", "9002", "9003", "9004", "9005", "9006", "9007"], 1):
            lines.append(
                f"vreg_abc123;Supplier A;Product X;elektriciteit;vast;"
                f"{pc};woning;1500.00;1815.00;315.00;2500.00;2026-08-29T10:00:00\n"
            )
        csv_path.write_text("".join(lines), encoding="utf-8-sig")

        # Import
        result = import_vtest_contract_en_prijzen(db_conn, self.VERSION_ID, csv_path)

        # Contract moet eenmaal ingevoegd zijn
        contracts = db_conn.execute(
            sa.select(sa.func.count(vtest_contract.c.vreg_id))
            .where(vtest_contract.c.vreg_id == "vreg_abc123")
        ).scalar()
        assert contracts == 1, "Contract moet eenmaal voorkomen"

        # Prijzen: alle 8 postcodes moeten ingevoegd zijn
        prijzen = db_conn.execute(
            sa.select(sa.func.count(vtest_postcode_prijs.c.id))
            .where(vtest_postcode_prijs.c.vreg_id == "vreg_abc123")
        ).scalar()
        assert prijzen == 8, f"Expected 8 postcode-prijsrijen, got {prijzen}"

        # Controleer dat alle postcodes aanwezig zijn
        postcodes = db_conn.execute(
            sa.select(vtest_postcode_prijs.c.postcode)
            .where(vtest_postcode_prijs.c.vreg_id == "vreg_abc123")
            .order_by(vtest_postcode_prijs.c.postcode)
        ).scalars().all()
        assert postcodes == ["9000", "9001", "9002", "9003", "9004", "9005", "9006", "9007"]
