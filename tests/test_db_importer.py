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
    _profiel_meta_uit_bestandsnaam,
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


class TestProfielMetaUitBestandsnaam:
    """Pure-Python: geen databankverbinding nodig."""

    def test_slp_ex_heeft_geen_energie_type(self):
        assert _profiel_meta_uit_bestandsnaam("slp_ex_2026.csv") == ("slp_ex", "", 2026)

    def test_spp_heeft_geen_energie_type(self):
        assert _profiel_meta_uit_bestandsnaam("spp_2026.csv") == ("spp", "", 2026)

    def test_rlp0n_elektriciteit(self):
        assert _profiel_meta_uit_bestandsnaam("rlp0n_elektriciteit_2026.csv") == (
            "rlp0n", "elektriciteit", 2026,
        )

    def test_rlp0n_gas(self):
        assert _profiel_meta_uit_bestandsnaam("rlp0n_gas_2026.csv") == ("rlp0n", "gas", 2026)

    def test_onbekend_voorvoegsel_faalt_hard(self):
        with pytest.raises(ValueError):
            _profiel_meta_uit_bestandsnaam("iets_onbekends_2026.csv")


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
        from datetime import date

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
        # echte tariefdata. Er wordt op het tariefjaar 2026 gefilterd en niet
        # meer op `geldig_tot IS NULL` — sinds migratie 0018 sluit een
        # tariefjaar af op 31 december en staat er geen enkele rij meer open.
        van_2026 = netbeheerder_tarief.c.geldig_van == date(2026, 1, 1)
        rows = db_conn.execute(
            sa.select(netbeheerder_tarief.c.contract_richting, netbeheerder_tarief.c.klanttype)
            .where(
                van_2026
                & netbeheerder_tarief.c.source_sheet.in_(
                    ["FA ELEK Afname", "FA ELEK Injectie"]
                )
                & (netbeheerder_tarief.c.tarieftype == "Netgebruik")
                | (
                    van_2026
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

    def test_tariefjaar_wordt_afgesloten_op_31_december(self, db_conn, tmp_path):
        """Een tariefjaar loopt tot en met 31 december, ook zonder opvolger.

        VREG stelt de distributienettarieven per kalenderjaar vast. Voorheen
        stond `geldig_tot` op NULL tot er een volgend jaar geïmporteerd werd;
        een berekening over 2027 kreeg dan stil de tarieven van 2026. Sinds
        migratie 0018 draagt elke rij haar eigen einddatum.

        De datum is inclusief (31/12), de conventie van deze tabel — niet de
        half-open vorm uit de gebruikerstabellen van migratie 0017.
        """
        import sqlalchemy as sa
        from datetime import date

        from energie_vlaanderen.infrastructure.db.schema import netbeheerder_tarief

        seed_netbeheerder(db_conn)

        header = "Netbeheerder;Contracttype;Tarieftype;Tariefdetail;source_sheet;source_row;Tariefnotering;Klanttype;Prijs_num\n"
        (tmp_path / "tariffs_electricity_afname.csv").write_text(
            header + "FA;Afname;Netgebruik;Laagspanning;FA ELEK LS;1;ct/kWh;ELEK_LV1;15.50\n",
            encoding="utf-8-sig",
        )

        # ELEK_LV1 bestaat niet in de echte tariefdata: de test blijft daarmee
        # onafhankelijk van wat er al in de gedeelde databank staat.
        def rijen():
            return db_conn.execute(
                sa.select(
                    netbeheerder_tarief.c.id,
                    netbeheerder_tarief.c.geldig_van,
                    netbeheerder_tarief.c.geldig_tot,
                )
                .where(
                    (netbeheerder_tarief.c.netbeheerder_code == "FA")
                    & (netbeheerder_tarief.c.klanttype == "ELEK_LV1")
                )
                .order_by(netbeheerder_tarief.c.geldig_van)
            ).all()

        import_netbeheerder_tarieven(db_conn, tmp_path, jaar=2026)
        ((id_2026, van, tot),) = rijen()
        assert van == date(2026, 1, 1)
        assert tot == date(2026, 12, 31)

        # Tweede import van hetzelfde jaar: bijwerken, geen tweede historiekrij.
        # Dit liep eerder stuk op uq_netbeheerder_tarief zodra de rij een
        # einddatum droeg, omdat de opzoeking op `geldig_tot IS NULL` niets
        # meer vond en doorviel naar een insert.
        import_netbeheerder_tarieven(db_conn, tmp_path, jaar=2026)
        assert len(rijen()) == 1

        # Volgend tariefjaar: nieuwe rij, de vorige blijft afgesloten staan.
        import_netbeheerder_tarieven(db_conn, tmp_path, jaar=2027)
        rows = rijen()
        assert len(rows) == 2
        assert rows[0].id == id_2026
        assert rows[0].geldig_tot == date(2026, 12, 31)
        assert rows[1].geldig_van == date(2027, 1, 1)
        assert rows[1].geldig_tot == date(2027, 12, 31)

    def test_geen_gat_of_overlap_tussen_twee_tariefjaren(self, db_conn, tmp_path):
        """De einddatum van het ene jaar sluit aan op de begindatum van het
        volgende: 31/12 gevolgd door 01/01, geen dag ertussen en geen dag dubbel."""
        import sqlalchemy as sa
        from datetime import date, timedelta

        from energie_vlaanderen.infrastructure.db.schema import netbeheerder_tarief

        seed_netbeheerder(db_conn)
        header = "Netbeheerder;Contracttype;Tarieftype;Tariefdetail;source_sheet;source_row;Tariefnotering;Klanttype;Prijs_num\n"
        (tmp_path / "tariffs_electricity_afname.csv").write_text(
            header + "FA;Afname;Netgebruik;Laagspanning;FA ELEK LS;1;ct/kWh;ELEK_LV2;15.50\n",
            encoding="utf-8-sig",
        )
        import_netbeheerder_tarieven(db_conn, tmp_path, jaar=2026)
        import_netbeheerder_tarieven(db_conn, tmp_path, jaar=2027)

        rows = db_conn.execute(
            sa.select(netbeheerder_tarief.c.geldig_van, netbeheerder_tarief.c.geldig_tot)
            .where(
                (netbeheerder_tarief.c.netbeheerder_code == "FA")
                & (netbeheerder_tarief.c.klanttype == "ELEK_LV2")
            )
            .order_by(netbeheerder_tarief.c.geldig_van)
        ).all()
        assert len(rows) == 2
        assert rows[0].geldig_tot + timedelta(days=1) == rows[1].geldig_van


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

    # -- contractmetadata ---------------------------------------------------
    #
    # `vtest_contract` stond in de praktijk grotendeels leeg: intekenperiode,
    # start levering, looptijd, doelgroep en de tariefkaartlink waren NULL.
    # Twee oorzaken, allebei stil:
    #   1. de scraper leverde ze niet aan (het detailpaneel van vtest.be
    #      bereikte de parser niet — zie tests/test_vtest_contractdetails.py);
    #   2. de upsert hier werkte bij een conflict alleen `laatst_gezien_*` bij,
    #      zodat een contract dat ooit leeg ingelezen was, leeg bleef.
    # De tests hieronder dekken (2).

    _META_HEADER = (
        "vreg_id;supplier_raw;product_raw;energy;tariff_type;postcode;segment;"
        "looptijd_tekst;looptijd_maanden;datum_intekenen_van;datum_intekenen_tot;"
        "doelgroep_zonnepanelen;link_tariefkaart;scraped_at\n"
    )

    def _import_meta_csv(self, db_conn, tmp_path, naam: str, rijen: list[str]):
        from energie_vlaanderen.infrastructure.db.importer import (
            import_vtest_contract_en_prijzen,
        )

        csv_path = tmp_path / naam
        csv_path.write_text(self._META_HEADER + "".join(rijen), encoding="utf-8-sig")
        return import_vtest_contract_en_prijzen(db_conn, self.VERSION_ID, csv_path)

    def test_metadata_wordt_alsnog_ingevuld_bij_herimport(self, db_conn, tmp_path):
        """Een contract dat leeg in de databank staat, moet bij een volgende
        import met detailgegevens wél gevuld raken."""
        import datetime as dt

        import sqlalchemy as sa

        from energie_vlaanderen.infrastructure.db.schema import vtest_contract

        self._seed_data_version(db_conn)
        zonder = (
            "vreg_meta1;Supplier A;Product X;elektriciteit;vast;9000;woning;"
            ";;;;;;2026-09-03T10:00:00\n"
        )
        met = (
            "vreg_meta1;Supplier A;Product X;elektriciteit;vast;9000;woning;"
            "1 jaar;12;2026-09-01;2026-09-30;Nee;https://voorbeeld.be/tk.pdf;"
            "2026-09-03T11:00:00\n"
        )

        self._import_meta_csv(db_conn, tmp_path, "leeg.csv", [zonder])
        rij = db_conn.execute(
            sa.select(vtest_contract).where(vtest_contract.c.vreg_id == "vreg_meta1")
        ).mappings().one()
        assert rij["datum_intekenen_van"] is None

        self._import_meta_csv(db_conn, tmp_path, "vol.csv", [met])
        rij = db_conn.execute(
            sa.select(vtest_contract).where(vtest_contract.c.vreg_id == "vreg_meta1")
        ).mappings().one()
        assert rij["datum_intekenen_van"] == dt.date(2026, 9, 1)
        assert rij["datum_intekenen_tot"] == dt.date(2026, 9, 30)
        assert rij["looptijd_tekst"] == "1 jaar"
        assert rij["looptijd_maanden"] == 12
        assert rij["doelgroep_zonnepanelen"] == "Nee"
        assert rij["link_tariefkaart"] == "https://voorbeeld.be/tk.pdf"

    def test_lege_herimport_wist_bestaande_metadata_niet(self, db_conn, tmp_path):
        """Afwezigheid is geen nieuwe waarde.

        Een run zonder --met-contractdetails levert lege velden. Die mogen de
        eerder opgehaalde metadata niet overschrijven — dat zou de gegevens
        stil weer wissen, met een geslaagde import als resultaat.
        """
        import datetime as dt

        import sqlalchemy as sa

        from energie_vlaanderen.infrastructure.db.schema import vtest_contract

        self._seed_data_version(db_conn)
        met = (
            "vreg_meta2;Supplier B;Product Y;elektriciteit;vast;9000;woning;"
            "2 jaar;24;2026-09-01;2026-09-30;Ja;https://voorbeeld.be/tk2.pdf;"
            "2026-09-03T11:00:00\n"
        )
        zonder = (
            "vreg_meta2;Supplier B;Product Y;elektriciteit;vast;9000;woning;"
            ";;;;;;2026-09-03T12:00:00\n"
        )

        self._import_meta_csv(db_conn, tmp_path, "vol2.csv", [met])
        self._import_meta_csv(db_conn, tmp_path, "leeg2.csv", [zonder])

        rij = db_conn.execute(
            sa.select(vtest_contract).where(vtest_contract.c.vreg_id == "vreg_meta2")
        ).mappings().one()
        assert rij["datum_intekenen_van"] == dt.date(2026, 9, 1)
        assert rij["looptijd_tekst"] == "2 jaar"
        assert rij["link_tariefkaart"] == "https://voorbeeld.be/tk2.pdf"

    def test_combinaties_vullen_elkaar_aan_binnen_een_import(self, db_conn, tmp_path):
        """Bij een hervatte matrixrun kan de eerste combinatie nog van vóór de
        contractdetails komen. "De eerste rij wint" zou het contract dan leeg
        laten terwijl een latere combinatie de gegevens wél draagt."""
        import datetime as dt

        import sqlalchemy as sa

        from energie_vlaanderen.infrastructure.db.schema import vtest_contract

        self._seed_data_version(db_conn)
        self._import_meta_csv(db_conn, tmp_path, "gemengd.csv", [
            "vreg_meta3;Supplier C;Product Z;elektriciteit;vast;9000;woning;"
            ";;;;;;2026-09-03T10:00:00\n",
            "vreg_meta3;Supplier C;Product Z;elektriciteit;vast;2000;woning;"
            "3 jaar;36;2026-09-01;2026-09-30;Nee;https://voorbeeld.be/tk3.pdf;"
            "2026-09-03T10:00:00\n",
        ])

        rij = db_conn.execute(
            sa.select(vtest_contract).where(vtest_contract.c.vreg_id == "vreg_meta3")
        ).mappings().one()
        assert rij["looptijd_tekst"] == "3 jaar"
        assert rij["datum_intekenen_van"] == dt.date(2026, 9, 1)
        assert rij["link_tariefkaart"] == "https://voorbeeld.be/tk3.pdf"

    # -- de tijdas (migratie 0019) -----------------------------------------
    #
    # `vtest_contract` had geen tijdas: de metadata werd bij elke import
    # overschreven, zodat je in 2028 de laatste beschrijving van een contract
    # uit september 2026 kreeg in plaats van die van toen. De tijdas ankert op
    # de **scrapedatum** — de dag waarop deze metadata bij vtest.be zo stond —
    # en niet op de publicatiedatum, die dagen later kan liggen en administratie
    # van deze toepassing is. Die staat apart in `gepubliceerd_op`.

    def _meta_rij(self, vreg_id: str, looptijd: str, tariefkaart: str, scrape: str) -> str:
        return (
            f"{vreg_id};Supplier T;Product T;elektriciteit;vast;9000;woning;"
            f"{looptijd};12;2026-09-01;2026-09-30;Nee;{tariefkaart};{scrape}\n"
        )

    def _snapshots(self, db_conn, vreg_id: str):
        import sqlalchemy as sa

        from energie_vlaanderen.infrastructure.db.schema import vtest_contract

        return db_conn.execute(
            sa.select(vtest_contract)
            .where(vtest_contract.c.vreg_id == vreg_id)
            .order_by(vtest_contract.c.geldig_van)
        ).mappings().all()

    def test_gewijzigde_metadata_geeft_een_nieuw_snapshot(self, db_conn, tmp_path):
        """De oude beschrijving blijft opvraagbaar, afgesloten op de dag vóór
        de nieuwe waarneming."""
        import datetime as dt

        self._seed_data_version(db_conn)
        self._import_meta_csv(db_conn, tmp_path, "t1.csv", [
            self._meta_rij("vreg_tijd1", "1 jaar", "https://x/oud.pdf", "2026-09-03T10:00:00"),
        ])
        self._import_meta_csv(db_conn, tmp_path, "t2.csv", [
            self._meta_rij("vreg_tijd1", "2 jaar", "https://x/nieuw.pdf", "2026-10-05T10:00:00"),
        ])

        rijen = self._snapshots(db_conn, "vreg_tijd1")
        assert len(rijen) == 2
        assert rijen[0]["geldig_van"] == dt.date(2026, 9, 3)
        assert rijen[0]["geldig_tot"] == dt.date(2026, 10, 4), "afgesloten op de dag ervóór"
        assert rijen[0]["looptijd_tekst"] == "1 jaar"
        assert rijen[0]["link_tariefkaart"] == "https://x/oud.pdf"
        assert rijen[1]["geldig_van"] == dt.date(2026, 10, 5)
        assert rijen[1]["geldig_tot"] is None
        assert rijen[1]["looptijd_tekst"] == "2 jaar"

    def test_ongewijzigde_hernieuwde_scrape_voegt_geen_snapshot_toe(self, db_conn, tmp_path):
        """Zonder deze regel zou elke scrape 355 rijen toevoegen zonder één
        extra feit, en zou de tabel binnen een jaar onbruikbaar groeien."""
        self._seed_data_version(db_conn)
        rij_sept = self._meta_rij("vreg_tijd2", "1 jaar", "https://x/a.pdf", "2026-09-03T10:00:00")
        rij_okt = self._meta_rij("vreg_tijd2", "1 jaar", "https://x/a.pdf", "2026-10-05T10:00:00")

        self._import_meta_csv(db_conn, tmp_path, "g1.csv", [rij_sept])
        self._import_meta_csv(db_conn, tmp_path, "g2.csv", [rij_okt])
        self._import_meta_csv(db_conn, tmp_path, "g3.csv", [rij_okt])

        rijen = self._snapshots(db_conn, "vreg_tijd2")
        assert len(rijen) == 1
        assert rijen[0]["geldig_tot"] is None

    def test_lege_velden_lokken_geen_nieuw_snapshot_uit(self, db_conn, tmp_path):
        """Afwezigheid is geen wijziging.

        Een run zonder detailpanelen levert lege velden. Die mogen noch de
        metadata overschrijven, noch een tweede snapshot uitlokken — anders
        krijgt elke prijs-only scrape een lege contractversie naast zich.
        """
        self._seed_data_version(db_conn)
        self._import_meta_csv(db_conn, tmp_path, "l1.csv", [
            self._meta_rij("vreg_tijd3", "1 jaar", "https://x/a.pdf", "2026-09-03T10:00:00"),
        ])
        self._import_meta_csv(db_conn, tmp_path, "l2.csv", [
            "vreg_tijd3;Supplier T;Product T;elektriciteit;vast;9000;woning;"
            ";;;;;;2026-10-05T10:00:00\n",
        ])

        rijen = self._snapshots(db_conn, "vreg_tijd3")
        assert len(rijen) == 1
        assert rijen[0]["looptijd_tekst"] == "1 jaar"
        assert rijen[0]["link_tariefkaart"] == "https://x/a.pdf"

    def test_de_beschrijving_op_een_datum_is_opvraagbaar(self, db_conn, tmp_path):
        """De vraag waar deze tijdas voor bestaat: hoe zag dit contract eruit
        op een dag in het verleden?"""
        import datetime as dt

        import sqlalchemy as sa

        from energie_vlaanderen.infrastructure.db.schema import vtest_contract

        self._seed_data_version(db_conn)
        self._import_meta_csv(db_conn, tmp_path, "d1.csv", [
            self._meta_rij("vreg_tijd4", "1 jaar", "https://x/a.pdf", "2026-09-03T10:00:00"),
        ])
        self._import_meta_csv(db_conn, tmp_path, "d2.csv", [
            self._meta_rij("vreg_tijd4", "3 jaar", "https://x/b.pdf", "2026-11-02T10:00:00"),
        ])

        def op(dag: dt.date) -> str | None:
            return db_conn.execute(
                sa.select(vtest_contract.c.looptijd_tekst).where(
                    (vtest_contract.c.vreg_id == "vreg_tijd4")
                    & (vtest_contract.c.geldig_van <= dag)
                    & (
                        vtest_contract.c.geldig_tot.is_(None)
                        | (vtest_contract.c.geldig_tot >= dag)
                    )
                )
            ).scalar()

        assert op(dt.date(2026, 9, 20)) == "1 jaar"
        assert op(dt.date(2026, 11, 1)) == "1 jaar", "de dag vóór de wissel"
        assert op(dt.date(2026, 11, 2)) == "3 jaar", "de dag van de wissel"
        assert op(dt.date(2028, 1, 1)) == "3 jaar"

    def test_geen_gat_of_overlap_tussen_twee_snapshots(self, db_conn, tmp_path):
        import datetime as dt

        self._seed_data_version(db_conn)
        self._import_meta_csv(db_conn, tmp_path, "o1.csv", [
            self._meta_rij("vreg_tijd5", "1 jaar", "https://x/a.pdf", "2026-09-03T10:00:00"),
        ])
        self._import_meta_csv(db_conn, tmp_path, "o2.csv", [
            self._meta_rij("vreg_tijd5", "2 jaar", "https://x/b.pdf", "2026-10-05T10:00:00"),
        ])
        rijen = self._snapshots(db_conn, "vreg_tijd5")
        assert rijen[0]["geldig_tot"] + dt.timedelta(days=1) == rijen[1]["geldig_van"]

    def test_publicatiedatum_blijft_leeg_tot_de_versie_gepubliceerd_is(
        self, db_conn, tmp_path
    ):
        """`gepubliceerd_op` wordt bij het activeren gezet, niet bij de import.

        `version publish` importeert eerst en activeert daarna, dus tijdens de
        import bestaat er nog geen publicatiemoment. Een versie die alleen met
        `db import` ingelezen is, is ook werkelijk niet gepubliceerd — NULL is
        daar de juiste uitspraak, geen ontbrekend gegeven.
        """
        self._seed_data_version(db_conn)
        self._import_meta_csv(db_conn, tmp_path, "p1.csv", [
            self._meta_rij("vreg_tijd6", "1 jaar", "https://x/a.pdf", "2026-09-03T10:00:00"),
        ])
        (rij,) = self._snapshots(db_conn, "vreg_tijd6")
        assert rij["gepubliceerd_op"] is None


@pytest.mark.integration
class TestImportMarktcurves:
    """De VREG-prijscurves werden wel geparsed maar nooit ingelezen:
    `marktcurve` stond leeg terwijl de CSV's al maanden in staging stonden.

    De cijfers hieronder komen uit `curves_*.csv` van staging-versie
    20260829T202059Z-853a7046 (VREG-werkboek energy_curves, augustus 2026).
    """

    VERSION_ID = "20260829T202059Z-853a7046"

    def _schrijf_curves(self, tmp_path):
        curves = tmp_path / "curves"
        curves.mkdir()
        (curves / "curves_spot.csv").write_text(
            "Groep;Parameter;Waarde;SourceSheet\n"
            "Elektriciteit - afname;Maandrekenkundig gemiddelde;128.55028;SPOT_waardes\n"
            "Gas TTF;Gewogen gemiddelde;31.20;SPOT_waardes\n",
            encoding="utf-8-sig",
        )
        (curves / "curves_forward.csv").write_text(
            "Datum;Energietype;Indexatieparameter;Afname_VNR;Teruglevering_VNR;SourceSheet\n"
            "2026-08-01T00:00:00;E;Endex 101;121.59674;106.86241;FORWARD_waardes\n",
            encoding="utf-8-sig",
        )
        (curves / "curves_timeseries.csv").write_text(
            "Timestamp;CurveType;EnergyType;Resolution;Variant;Waarde;SourceSheet\n"
            "2026-09-01T00:00:00;EPC;Elektriciteit;1H;EPC elektriciteit;140.194618029201;EPC_Elek\n"
            "2026-09-01T01:00:00;SPP;Elektriciteit_Injectie;15Min;SPP;0.0;SPP\n",
            encoding="utf-8-sig",
        )
        return tmp_path

    def _seed_data_version(self, db_conn) -> None:
        import sqlalchemy as sa

        from energie_vlaanderen.infrastructure.db.schema import data_version

        db_conn.execute(
            sa.dialects.postgresql.insert(data_version)
            .values(version_id=self.VERSION_ID, aangemaakt_op=sa.func.now())
            .on_conflict_do_nothing(index_elements=["version_id"])
        )

    def test_alle_drie_de_bestanden_landen_in_marktcurve(self, db_conn, tmp_path):
        import sqlalchemy as sa

        from energie_vlaanderen.infrastructure.db.importer import import_marktcurves
        from energie_vlaanderen.infrastructure.db.schema import marktcurve

        self._seed_data_version(db_conn)
        bron = self._schrijf_curves(tmp_path)
        result = import_marktcurves(db_conn, bron, self.VERSION_ID)

        # 2 spot + 2 forward (afname én teruglevering uit één bronrij) + 2 reeks
        assert result.rows_inserted == 6
        types = db_conn.execute(
            sa.select(marktcurve.c.curve_type)
            .where(marktcurve.c.version_id == self.VERSION_ID)
            .distinct()
        ).scalars().all()
        assert set(types) == {"spot", "forward", "EPC", "SPP"}

    def test_forward_wordt_twee_rijen(self, db_conn, tmp_path):
        """Afname en teruglevering zijn aparte grootheden.

        Eén bronrij draagt beide in twee kolommen; ze in één rij persen zou er
        stil een van de twee laten vallen.
        """
        import sqlalchemy as sa
        from decimal import Decimal

        from energie_vlaanderen.infrastructure.db.importer import import_marktcurves
        from energie_vlaanderen.infrastructure.db.schema import marktcurve

        self._seed_data_version(db_conn)
        import_marktcurves(db_conn, self._schrijf_curves(tmp_path), self.VERSION_ID)

        rows = db_conn.execute(
            sa.select(marktcurve.c.groep, marktcurve.c.waarde, marktcurve.c.datum)
            .where(
                (marktcurve.c.version_id == self.VERSION_ID)
                & (marktcurve.c.curve_type == "forward")
            )
            .order_by(marktcurve.c.groep)
        ).all()
        assert [r.groep for r in rows] == ["afname", "teruglevering"]
        assert rows[0].waarde == Decimal("121.596740")
        assert rows[1].waarde == Decimal("106.862410")

    def test_energievorm_wordt_genormaliseerd(self, db_conn, tmp_path):
        """Het werkboek schrijft de energievorm in vier vormen door elkaar:
        "E"/"G", voluit, als voorvoegsel ("Gas TTF") en met een richting
        erachter ("Elektriciteit_Injectie"). Ongenormaliseerd levert een
        filter op "gas" niets op."""
        import sqlalchemy as sa

        from energie_vlaanderen.infrastructure.db.importer import import_marktcurves
        from energie_vlaanderen.infrastructure.db.schema import marktcurve

        self._seed_data_version(db_conn)
        import_marktcurves(db_conn, self._schrijf_curves(tmp_path), self.VERSION_ID)

        soorten = db_conn.execute(
            sa.select(marktcurve.c.energie_type)
            .where(marktcurve.c.version_id == self.VERSION_ID)
            .distinct()
        ).scalars().all()
        assert set(soorten) == {"elektriciteit", "gas"}

    def test_herimport_verdubbelt_niet(self, db_conn, tmp_path):
        """`marktcurve` heeft geen unieke sleutel — een tweede import zou
        alles verdubbelen. Een versie levert haar curves in hun geheel, dus
        wordt eerst verwijderd wat er van die versie stond."""
        import sqlalchemy as sa

        from energie_vlaanderen.infrastructure.db.importer import import_marktcurves
        from energie_vlaanderen.infrastructure.db.schema import marktcurve

        self._seed_data_version(db_conn)
        bron = self._schrijf_curves(tmp_path)
        import_marktcurves(db_conn, bron, self.VERSION_ID)
        import_marktcurves(db_conn, bron, self.VERSION_ID)

        aantal = db_conn.execute(
            sa.select(sa.func.count()).select_from(marktcurve)
            .where(marktcurve.c.version_id == self.VERSION_ID)
        ).scalar()
        assert aantal == 6

    def test_ontbrekende_curvesmap_is_geen_fout(self, db_conn, tmp_path):
        from energie_vlaanderen.infrastructure.db.importer import import_marktcurves

        self._seed_data_version(db_conn)
        result = import_marktcurves(db_conn, tmp_path, self.VERSION_ID)
        assert result.rows_inserted == 0
