"""Tests voor de opslaglaag van de gebruikersbasis.

SQLite in het geheugen, zoals `tests/test_db_scd2.py`: de logica is
dialectonafhankelijk omdat `GebruikersRepository` bewust geen
`postgresql.insert(...).on_conflict_do_update()` gebruikt maar lezen-dan-
schrijven op de primaire sleutel doet.

Twee aanpassingen aan het schema, allebei omdat SQLite iets niet kan:
autoincrement op BIGINT, en `sa.func.now()` als server_default op een
TIMESTAMP-kolom.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal as D

import pytest

pytest.importorskip("sqlalchemy")

import sqlalchemy as sa

from energie_vlaanderen.gebruikers.models import (
    Aanname,
    Aansluitingspunt,
    AssetType,
    Contracttype,
    EnergieType,
    Exactheidsklasse,
    Gebruiker,
    InstallatieAsset,
    Leveringscontract,
    Meter,
    Meterregime,
    OpgaveBron,
    Persoonsgegevens,
    Registerschema,
    Segment,
    Topologie,
    Verbruiksopgave,
)
from energie_vlaanderen.gebruikers.repository import GebruikersRepository
from energie_vlaanderen.infrastructure.db import schema

TABELLEN = (
    "gebruiker",
    "gebruiker_persoonsgegeven",
    "aansluitingspunt",
    "meter",
    "installatie_asset",
    "leveringscontract",
    "verbruiksopgave",
    "toestemming",
    "meterinterval",
    "simulatie",
    "simulatie_regel",
)


@pytest.fixture
def conn():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()

    for naam in TABELLEN:
        origineel = schema.metadata.tables[naam]
        kolommen = []
        for kolom in origineel.columns:
            soort = kolom.type
            if isinstance(soort, sa.BigInteger):
                soort = sa.Integer()  # SQLite kan geen autoincrement op BIGINT
            kolommen.append(
                sa.Column(
                    kolom.name,
                    soort,
                    primary_key=kolom.primary_key,
                    nullable=kolom.nullable,
                )
            )
        sa.Table(naam, metadata, *kolommen)

    with engine.begin() as verbinding:
        metadata.create_all(verbinding)
        yield verbinding


@pytest.fixture
def dossier():
    gebruiker = Gebruiker(segment=Segment.WONING)
    punt = Aansluitingspunt(
        gebruiker_id=gebruiker.id,
        energie_type=EnergieType.ELEKTRICITEIT,
        postcode="9300",
        gemeente="Aalst",
        netbeheerder_code="FMV",
    )
    return gebruiker, punt


class TestRondrit:
    def test_gebruiker_en_persoonsgegevens_gaan_apart_de_databank_in(self, conn, dossier):
        """De scheiding is het punt: een berekening hoeft de PII-tabel nooit te lezen."""
        gebruiker, _ = dossier
        repo = GebruikersRepository(conn)
        repo.bewaar_gebruiker(
            gebruiker,
            Persoonsgegevens(gebruiker.id, naam="Test", postcode="9300", gemeente="Aalst"),
        )

        terug = repo.gebruiker(gebruiker.id)
        assert terug.id == gebruiker.id
        assert terug.segment is Segment.WONING
        assert not hasattr(terug, "naam")

        pii = repo.persoonsgegevens(gebruiker.id)
        assert pii.naam == "Test"

    def test_aansluitingspunt_meter_en_contract_komen_ongewijzigd_terug(self, conn, dossier):
        gebruiker, punt = dossier
        repo = GebruikersRepository(conn)
        repo.bewaar_gebruiker(gebruiker)
        repo.bewaar_aansluitingspunt(punt)
        repo.bewaar_meter(
            Meter(
                punt.id,
                meterregime=Meterregime.KLASSIEK,
                registerschema=Registerschema.EXCLUSIEF_NACHT,
                terugdraaiend=True,
            )
        )
        repo.bewaar_contract(
            Leveringscontract(
                punt.id,
                "Bolt",
                "Bolt Vast",
                Contracttype.VAST,
                date(2026, 1, 1),
                date(2026, 8, 1),
                tariefkaart_geldig_van=date(2026, 1, 1),
            )
        )

        (terug_punt,) = repo.aansluitingspunten(gebruiker.id)
        assert terug_punt.postcode == "9300"
        assert terug_punt.netbeheerder_code == "FMV"
        assert terug_punt.energie_type is EnergieType.ELEKTRICITEIT

        (terug_meter,) = repo.meters(punt.id)
        assert terug_meter.meterregime is Meterregime.KLASSIEK
        assert terug_meter.registerschema is Registerschema.EXCLUSIEF_NACHT
        assert terug_meter.terugdraaiend is True
        # De twee piekvelden zijn verhuisd van `gebruiker` naar `meter` maar
        # blijven twee aparte getallen (migratie 0015 haalde ze uit elkaar).
        assert terug_meter.geschatte_maandpiek_kw == D("4.218")
        assert terug_meter.minimum_maandpiek_kw == D("2.5")

        (terug_contract,) = repo.contracten(punt.id)
        assert terug_contract.prijs_bevriest
        assert terug_contract.tariefkaart_geldig_van == date(2026, 1, 1)

    def test_elektriciteit_en_gas_blijven_aparte_punten(self, conn, dossier):
        gebruiker, elek = dossier
        gas = Aansluitingspunt(gebruiker.id, EnergieType.GAS, "9300", "Aalst")
        repo = GebruikersRepository(conn)
        repo.bewaar_gebruiker(gebruiker)
        repo.bewaar_aansluitingspunt(elek)
        repo.bewaar_aansluitingspunt(gas)

        assert len(repo.aansluitingspunten(gebruiker.id)) == 2
        (alleen_gas,) = repo.aansluitingspunten(gebruiker.id, "gas")
        assert alleen_gas.id == gas.id

    def test_verbruiksopgave_bewaart_haar_aannames(self, conn, dossier):
        """De aannames reizen mee tot in de databank, niet alleen tot in het rapport."""
        gebruiker, punt = dossier
        repo = GebruikersRepository(conn)
        repo.bewaar_gebruiker(gebruiker)
        repo.bewaar_aansluitingspunt(punt)
        repo.bewaar_verbruiksopgave(
            Verbruiksopgave(
                punt.id,
                date(2026, 1, 1),
                date(2027, 1, 1),
                afname_dag_kwh=D("2000"),
                afname_nacht_kwh=D("1000"),
                bron=OpgaveBron.MANUEEL,
                aannames=(
                    Aanname(veld="pv_kwp", waarde="5.0", bron="omvormer_kva"),
                ),
            )
        )

        (terug,) = repo.verbruiksopgaven(punt.id)
        assert terug.afname_kwh == D("3000")
        assert terug.exactheidsklasse is Exactheidsklasse.GERECONSTRUEERD
        assert terug.aannames[0].veld == "pv_kwp"

    def test_asset_behoudt_zijn_topologie(self, conn, dossier):
        gebruiker, punt = dossier
        repo = GebruikersRepository(conn)
        repo.bewaar_gebruiker(gebruiker)
        repo.bewaar_aansluitingspunt(punt)
        repo.bewaar_asset(
            InstallatieAsset(
                punt.id,
                AssetType.BATTERIJ,
                merk="Marstek",
                model="Venus E",
                topologie=Topologie.HYBRIDE,
            )
        )
        (terug,) = repo.assets(punt.id)
        assert terug.topologie is Topologie.HYBRIDE


class TestIdempotentie:
    def test_twee_keer_bewaren_geeft_één_rij(self, conn, dossier):
        """Een tweede import van hetzelfde dossier mag niets veranderen."""
        gebruiker, punt = dossier
        repo = GebruikersRepository(conn)
        for _ in range(2):
            repo.bewaar_gebruiker(gebruiker)
            repo.bewaar_aansluitingspunt(punt)

        assert len(repo.gebruikers()) == 1
        assert len(repo.aansluitingspunten(gebruiker.id)) == 1

    def test_bewaren_werkt_bestaande_waarden_bij(self, conn, dossier):
        from dataclasses import replace

        gebruiker, punt = dossier
        repo = GebruikersRepository(conn)
        repo.bewaar_gebruiker(gebruiker)
        repo.bewaar_aansluitingspunt(punt)
        repo.bewaar_aansluitingspunt(replace(punt, gemeente="Erpe-Mere"))

        (terug,) = repo.aansluitingspunten(gebruiker.id)
        assert terug.gemeente == "Erpe-Mere"


class TestMetingen:
    def _rijen(self, aantal: int):
        from datetime import timedelta

        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return [
            {
                "tijdstip": start + timedelta(minutes=15 * i),
                "afname_kwh": D("0.25"),
                "injectie_kwh": D("0"),
            }
            for i in range(aantal)
        ]

    def test_metingen_gaan_er_gebatcht_in_en_komen_gesorteerd_terug(self, conn, dossier):
        gebruiker, punt = dossier
        repo = GebruikersRepository(conn)
        repo.bewaar_gebruiker(gebruiker)
        repo.bewaar_aansluitingspunt(punt)

        aantal = repo.importeer_metingen(punt.id, self._rijen(96), "fluvius.csv")
        assert aantal == 96

        terug = repo.metingen(punt.id)
        assert len(terug) == 96
        assert terug == sorted(terug, key=lambda r: r["tijdstip"])

    def test_dezelfde_import_twee_keer_verdubbelt_niets(self, conn, dossier):
        """Anders zou een tweede import het verbruik verdubbelen."""
        gebruiker, punt = dossier
        repo = GebruikersRepository(conn)
        repo.bewaar_gebruiker(gebruiker)
        repo.bewaar_aansluitingspunt(punt)

        repo.importeer_metingen(punt.id, self._rijen(96), "fluvius.csv")
        repo.importeer_metingen(punt.id, self._rijen(96), "fluvius.csv")

        assert len(repo.metingen(punt.id)) == 96

    def test_een_deelimport_wist_de_rest_niet(self, conn, dossier):
        """Verwijderen gebeurt alleen binnen het bereik dat de invoer dekt."""
        gebruiker, punt = dossier
        repo = GebruikersRepository(conn)
        repo.bewaar_gebruiker(gebruiker)
        repo.bewaar_aansluitingspunt(punt)

        repo.importeer_metingen(punt.id, self._rijen(96), "januari.csv")
        eerste_dag = self._rijen(4)
        repo.importeer_metingen(punt.id, eerste_dag, "correctie.csv")

        assert len(repo.metingen(punt.id)) == 96


class TestSimulatie:
    def test_een_simulatie_bewaart_haar_exactheidsklasse_en_regels(self, conn, dossier):
        """Zonder klasse, bronversies en aannames is een bedrag niet te beoordelen."""
        gebruiker, punt = dossier
        repo = GebruikersRepository(conn)
        repo.bewaar_gebruiker(gebruiker)
        repo.bewaar_aansluitingspunt(punt)

        simulatie_id = repo.bewaar_simulatie(
            gebruiker_id=gebruiker.id,
            aansluitingspunt_id=punt.id,
            periode_van=date(2026, 1, 1),
            periode_tot=date(2027, 1, 1),
            totalen={"supplier": D("562.21"), "totaal": D("1141.36")},
            exactheidsklasse=Exactheidsklasse.GESCHAT,
            regels=[
                {
                    "periode_van": date(2026, 1, 1),
                    "periode_tot": date(2026, 8, 1),
                    "leverancier": "Bolt",
                    "product": "Bolt Vast",
                    "totaal_eur": D("652.82"),
                    "exactheidsklasse": "geschat",
                    "redenen": ["venstergrens"],
                }
            ],
            aannames=[Aanname(veld="pv_kwp", waarde="5.0", bron="omvormer_kva")],
        )

        rij = conn.execute(
            sa.select(schema.simulatie.c.exactheidsklasse, schema.simulatie.c.totaal_eur).where(
                schema.simulatie.c.id == simulatie_id
            )
        ).first()
        assert rij[0] == "geschat"
        assert D(str(rij[1])) == D("1141.36")

        regels = conn.execute(sa.select(schema.simulatie_regel)).mappings().all()
        assert len(regels) == 1
        assert regels[0]["leverancier"] == "Bolt"
