"""Gebruikersbasis: gebruikers, aansluitingspunten, meters en contracten.

Vervangt het lege scaffold uit migratie 0001 (`gebruiker`, `meterinterval`,
`simulatie`, bijgewerkt door 0015) door het model uit `docs/manifest.md`
§5.1-5.4 en `ROADMAP.md` Fase 1. De drie scaffoldtabellen zijn nooit door een
importer gevuld; ze worden hier gedropt en opnieuw gebouwd in plaats van
omgevormd, omdat er geen rij is om te bewaren.

Wat er in het oude model niet paste:

- **EAN.** Eén EAN identificeert één toegangspunt voor één energiedrager.
  Elektriciteit en gas zijn aparte EAN's en dus aparte rijen in
  `aansluitingspunt`. Injectie is géén aparte EAN maar een aparte
  registerlezing op dezelfde meter. Het oude `gebruiker` had één `meter_type`
  en geen EAN, en kon een gebruiker met gas én elektriciteit niet beschrijven.
- **Contractperiodes.** `huidig_leverancier`/`huidig_product`/
  `contract_startdatum` waren drie kolommen op de gebruiker: geen einddatum,
  geen opvolging, en geen plaats voor de bevroren tariefkaart van een vast
  contract. Dat laatste is de kern van een correcte historische kost — een
  vast contract volgt de actuele tariefkaart niet.
- **Persoonsgegevens.** Manifest §4.3 vraagt doelbinding, encryptie en een
  verwijdermogelijkheid. Naam en adres staan daarom in een eigen tabel, zodat
  een berekening ze nooit hoeft aan te raken en verwijderen één DELETE is.

Verplaatsingen die opvallen:

- `geschatte_maandpiek_kw`/`minimum_maandpiek_kw` gaan van `gebruiker` naar
  `meter`. Ze blijven `Numeric(7, 3)` — op twee decimalen zou de
  vtest-standaardpiek 4,218 stil 4,22 worden — en blijven twee aparte
  kolommen, precies zoals migratie 0015 ze uit elkaar haalde. Ze horen bij de
  meter omdat de ondergrens van 2,5 kW aan het meetregime hangt, niet aan het
  verbruik.
- `meterinterval` hangt aan `aansluitingspunt_id` in plaats van aan
  `gebruiker_id`: een meting hoort bij een toegangspunt.

Sleutels zijn UUID's en geen oplopende getallen: deze id's verlaten straks het
systeem via export en API, en mogen dan niet verraden hoeveel gebruikers er
zijn of wie eerder kwam.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-02 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # De drie scaffoldtabellen in omgekeerde afhankelijkheidsvolgorde weg.
    op.drop_table("simulatie")
    op.drop_table("meterinterval")
    op.drop_table("gebruiker")

    op.create_table(
        "gebruiker",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("segment", sa.Text, nullable=False, server_default="Woning"),
        sa.Column("land", sa.String(2), nullable=False, server_default="BE"),
        sa.Column("toestemming_referentie", sa.Text, nullable=True),
        sa.Column("aangemaakt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("bijgewerkt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "gebruiker_persoonsgegeven",
        sa.Column("gebruiker_id", sa.Uuid, sa.ForeignKey("gebruiker.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("naam", sa.Text, nullable=False, server_default=""),
        sa.Column("email", sa.Text, nullable=False, server_default=""),
        sa.Column("straat", sa.Text, nullable=False, server_default=""),
        sa.Column("huisnummer", sa.Text, nullable=False, server_default=""),
        sa.Column("postcode", sa.String(10), nullable=False, server_default=""),
        sa.Column("gemeente", sa.Text, nullable=False, server_default=""),
        sa.Column("bijgewerkt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "aansluitingspunt",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("gebruiker_id", sa.Uuid, sa.ForeignKey("gebruiker.id", ondelete="CASCADE"), nullable=False),
        sa.Column("energie_type", sa.Text, nullable=False),
        sa.Column("ean_code", sa.String(18), nullable=True, unique=True),
        sa.Column("postcode", sa.String(10), sa.ForeignKey("gemeente.postcode"), nullable=False),
        sa.Column("gemeente_naam", sa.Text, nullable=False, server_default=""),
        sa.Column("netbeheerder_code", sa.String(40), sa.ForeignKey("netbeheerder.code"), nullable=True),
        sa.Column("spanningsniveau", sa.Text, nullable=False, server_default="laag"),
        sa.Column("aansluitingsvermogen_kva", sa.Numeric(9, 3), nullable=True),
        sa.Column("aantal_fasen", sa.SmallInteger, nullable=True),
        sa.Column("geldig_van", sa.Date, nullable=True),
        sa.Column("geldig_tot", sa.Date, nullable=True),
        sa.Column("aangemaakt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_aansluitingspunt_gebruiker", "aansluitingspunt", ["gebruiker_id", "energie_type"])

    op.create_table(
        "meter",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("aansluitingspunt_id", sa.Uuid, sa.ForeignKey("aansluitingspunt.id", ondelete="CASCADE"), nullable=False),
        sa.Column("meterregime", sa.Text, nullable=False, server_default="digitaal"),
        sa.Column("registerschema", sa.Text, nullable=False, server_default="enkelvoudig"),
        sa.Column("terugdraaiend", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("geschatte_maandpiek_kw", sa.Numeric(7, 3), nullable=False, server_default="4.218"),
        sa.Column("minimum_maandpiek_kw", sa.Numeric(7, 3), nullable=False, server_default="2.5"),
        sa.Column("geldig_van", sa.Date, nullable=True),
        sa.Column("geldig_tot", sa.Date, nullable=True),
    )
    op.create_index("ix_meter_aansluitingspunt", "meter", ["aansluitingspunt_id"])

    op.create_table(
        "installatie_asset",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("aansluitingspunt_id", sa.Uuid, sa.ForeignKey("aansluitingspunt.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("merk", sa.Text, nullable=False, server_default=""),
        sa.Column("model", sa.Text, nullable=False, server_default=""),
        sa.Column("kwp", sa.Numeric(9, 3), nullable=True),
        sa.Column("omvormer_merk", sa.Text, nullable=False, server_default=""),
        sa.Column("omvormer_model", sa.Text, nullable=False, server_default=""),
        sa.Column("omvormer_kva", sa.Numeric(9, 3), nullable=True),
        sa.Column("topologie", sa.Text, nullable=True),
        sa.Column("geldig_van", sa.Date, nullable=True),
        sa.Column("geldig_tot", sa.Date, nullable=True),
    )
    op.create_index("ix_installatie_asset_aansluitingspunt", "installatie_asset", ["aansluitingspunt_id", "type"])

    op.create_table(
        "leveringscontract",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("aansluitingspunt_id", sa.Uuid, sa.ForeignKey("aansluitingspunt.id", ondelete="CASCADE"), nullable=False),
        sa.Column("leverancier", sa.Text, nullable=False),
        sa.Column("product", sa.Text, nullable=False, server_default=""),
        sa.Column("vreg_id", sa.Text, nullable=True),
        sa.Column("contracttype", sa.Text, nullable=False),
        sa.Column("geldig_van", sa.Date, nullable=False),
        sa.Column("geldig_tot", sa.Date, nullable=True),
        sa.Column("tariefkaart_geldig_van", sa.Date, nullable=True),
        sa.Column("bron", sa.Text, nullable=False, server_default=""),
    )
    op.create_index(
        "ix_leveringscontract_lookup", "leveringscontract",
        ["aansluitingspunt_id", "geldig_van", "geldig_tot"],
    )

    op.create_table(
        "verbruiksopgave",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("aansluitingspunt_id", sa.Uuid, sa.ForeignKey("aansluitingspunt.id", ondelete="CASCADE"), nullable=False),
        sa.Column("periode_van", sa.Date, nullable=False),
        sa.Column("periode_tot", sa.Date, nullable=False),
        sa.Column("afname_dag_kwh", sa.Numeric(12, 3), nullable=False, server_default="0"),
        sa.Column("afname_nacht_kwh", sa.Numeric(12, 3), nullable=False, server_default="0"),
        sa.Column("afname_exclusief_nacht_kwh", sa.Numeric(12, 3), nullable=False, server_default="0"),
        sa.Column("injectie_dag_kwh", sa.Numeric(12, 3), nullable=False, server_default="0"),
        sa.Column("injectie_nacht_kwh", sa.Numeric(12, 3), nullable=False, server_default="0"),
        sa.Column("bron", sa.Text, nullable=False, server_default="manueel"),
        sa.Column("dekkingsgraad", sa.Numeric(5, 4), nullable=False, server_default="1"),
        sa.Column("aannames", sa.JSON, nullable=False, server_default="[]"),
        sa.UniqueConstraint(
            "aansluitingspunt_id", "periode_van", "periode_tot", "bron",
            name="uq_verbruiksopgave_periode",
        ),
    )

    op.create_table(
        "toestemming",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("gebruiker_id", sa.Uuid, sa.ForeignKey("gebruiker.id", ondelete="CASCADE"), nullable=False),
        sa.Column("doel", sa.Text, nullable=False),
        sa.Column("verleend_op", sa.Date, nullable=False),
        sa.Column("ingetrokken_op", sa.Date, nullable=True),
        sa.Column("bron", sa.Text, nullable=False, server_default=""),
    )
    op.create_index("ix_toestemming_gebruiker", "toestemming", ["gebruiker_id", "doel"])

    op.create_table(
        "meterinterval",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("aansluitingspunt_id", sa.Uuid, sa.ForeignKey("aansluitingspunt.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tijdstip", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("afname_kwh", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("injectie_kwh", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("kwaliteitscode", sa.Text, nullable=False, server_default=""),
        sa.Column("bron_bestand", sa.Text, nullable=True),
        sa.Column("aangemaakt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("aansluitingspunt_id", "tijdstip", name="uq_meterinterval_punt_tijdstip"),
    )

    op.create_table(
        "simulatie",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("gebruiker_id", sa.Uuid, sa.ForeignKey("gebruiker.id", ondelete="CASCADE"), nullable=False),
        sa.Column("aansluitingspunt_id", sa.Uuid, sa.ForeignKey("aansluitingspunt.id", ondelete="CASCADE"), nullable=True),
        sa.Column("version_id", sa.String(26), sa.ForeignKey("data_version.version_id"), nullable=True),
        sa.Column("vreg_id", sa.Text, nullable=True),
        sa.Column("leverancier", sa.Text, nullable=True),
        sa.Column("product", sa.Text, nullable=True),
        sa.Column("periode_van", sa.Date, nullable=True),
        sa.Column("periode_tot", sa.Date, nullable=True),
        sa.Column("supplier_eur", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("grid_eur", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("levies_eur", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("injection_credit_eur", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("vat_eur", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("totaal_eur", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("exactheidsklasse", sa.Text, nullable=False, server_default="geschat"),
        sa.Column("bronversies", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("aannames", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("warnings", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("aangemaakt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "simulatie_regel",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("simulatie_id", sa.Uuid, sa.ForeignKey("simulatie.id", ondelete="CASCADE"), nullable=False),
        sa.Column("periode_van", sa.Date, nullable=False),
        sa.Column("periode_tot", sa.Date, nullable=False),
        sa.Column("leverancier", sa.Text, nullable=False, server_default=""),
        sa.Column("product", sa.Text, nullable=False, server_default=""),
        sa.Column("supplier_eur", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("grid_eur", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("levies_eur", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("injection_credit_eur", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("vat_eur", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("totaal_eur", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("exactheidsklasse", sa.Text, nullable=False, server_default="geschat"),
        sa.Column("redenen", sa.JSON, nullable=False, server_default="[]"),
    )
    op.create_index("ix_simulatie_regel_simulatie", "simulatie_regel", ["simulatie_id", "periode_van"])


def downgrade() -> None:
    """Herstelt het scaffold zoals 0001/0015 het achterlieten.

    De teruggedraaide tabellen zijn leeg: de gebruikersgegevens die 0017
    mogelijk maakte, gaan bij een downgrade verloren. Dat is bewust — ze in het
    oude platte model persen zou EAN's, tweede energiedragers en
    contracthistoriek stil weggooien, en dat is erger dan een lege tabel.
    """
    op.drop_index("ix_simulatie_regel_simulatie", table_name="simulatie_regel")
    op.drop_table("simulatie_regel")
    op.drop_table("simulatie")
    op.drop_table("meterinterval")
    op.drop_index("ix_toestemming_gebruiker", table_name="toestemming")
    op.drop_table("toestemming")
    op.drop_table("verbruiksopgave")
    op.drop_index("ix_leveringscontract_lookup", table_name="leveringscontract")
    op.drop_table("leveringscontract")
    op.drop_index("ix_installatie_asset_aansluitingspunt", table_name="installatie_asset")
    op.drop_table("installatie_asset")
    op.drop_index("ix_meter_aansluitingspunt", table_name="meter")
    op.drop_table("meter")
    op.drop_index("ix_aansluitingspunt_gebruiker", table_name="aansluitingspunt")
    op.drop_table("aansluitingspunt")
    op.drop_table("gebruiker_persoonsgegeven")
    op.drop_table("gebruiker")

    op.create_table(
        "gebruiker",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("naam", sa.Text, nullable=True),
        sa.Column("postcode", sa.String(10), sa.ForeignKey("gemeente.postcode"), nullable=True),
        sa.Column("segment", sa.Text, nullable=False, server_default="Woning"),
        sa.Column("meter_type", sa.Text, nullable=False, server_default="digitaal"),
        sa.Column("zonnepanelen", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("omvormer_kva", sa.Numeric(6, 2), nullable=True),
        sa.Column("afname_dag_kwh", sa.Numeric(10, 2), server_default="0"),
        sa.Column("afname_nacht_kwh", sa.Numeric(10, 2), server_default="0"),
        sa.Column("injectie_dag_kwh", sa.Numeric(10, 2), server_default="0"),
        sa.Column("injectie_nacht_kwh", sa.Numeric(10, 2), server_default="0"),
        sa.Column("geschatte_maandpiek_kw", sa.Numeric(7, 3), server_default="4.218"),
        sa.Column("minimum_maandpiek_kw", sa.Numeric(7, 3), server_default="2.5"),
        sa.Column("huidig_leverancier", sa.Text, nullable=True),
        sa.Column("huidig_product", sa.Text, nullable=True),
        sa.Column("contract_startdatum", sa.Date, nullable=True),
        sa.Column("aangemaakt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("bijgewerkt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "meterinterval",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("gebruiker_id", sa.Integer, sa.ForeignKey("gebruiker.id"), nullable=False),
        sa.Column("tijdstip", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("afname_kwh", sa.Numeric(8, 4), nullable=False, server_default="0"),
        sa.Column("injectie_kwh", sa.Numeric(8, 4), nullable=False, server_default="0"),
        sa.Column("bron_bestand", sa.Text, nullable=True),
        sa.Column("aangemaakt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("gebruiker_id", "tijdstip", name="uq_meterinterval_gebruiker_tijdstip"),
    )
    op.create_table(
        "simulatie",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("gebruiker_id", sa.Integer, sa.ForeignKey("gebruiker.id"), nullable=False),
        sa.Column("version_id", sa.String(26), sa.ForeignKey("data_version.version_id"), nullable=True),
        sa.Column("vreg_id", sa.Text, nullable=True),
        sa.Column("leverancier", sa.Text, nullable=True),
        sa.Column("product", sa.Text, nullable=True),
        sa.Column("periode_van", sa.Date, nullable=True),
        sa.Column("periode_tot", sa.Date, nullable=True),
        sa.Column("supplier_eur", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("grid_eur", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("levies_eur", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("injection_credit_eur", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("vat_eur", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("totaal_eur", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("warnings", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("aangemaakt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
