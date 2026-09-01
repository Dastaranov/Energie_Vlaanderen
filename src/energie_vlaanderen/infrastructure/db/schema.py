from __future__ import annotations

import sqlalchemy as sa

metadata = sa.MetaData()

# ---------------------------------------------------------------------------
# Groep 1 — Referentiedata (geen version_id)
# ---------------------------------------------------------------------------

netbeheerder = sa.Table(
    "netbeheerder",
    metadata,
    sa.Column("code", sa.String(40), primary_key=True),
    sa.Column("naam", sa.Text, nullable=False),
    sa.Column("bijgewerkt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
)

gemeente = sa.Table(
    "gemeente",
    metadata,
    sa.Column("postcode", sa.String(10), primary_key=True),
    sa.Column("naam", sa.Text, nullable=False),
    sa.Column("dnb_elektriciteit", sa.String(40), sa.ForeignKey("netbeheerder.code"), nullable=True),
    sa.Column("dnb_gas", sa.String(40), sa.ForeignKey("netbeheerder.code"), nullable=True),
    sa.Column("gastype_oud", sa.String(20), nullable=True),
    sa.Column("gastype_nieuw", sa.String(20), nullable=True),
    sa.Column("bijgewerkt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
)

# ---------------------------------------------------------------------------
# Groep 2 — Versiebeheer
# ---------------------------------------------------------------------------

data_version = sa.Table(
    "data_version",
    metadata,
    sa.Column("version_id", sa.String(26), primary_key=True),
    sa.Column("aangemaakt_op", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("geactiveerd_op", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("status", sa.Text, nullable=False, server_default="staged"),
    sa.Column("geimporteerd_op", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("notities", sa.Text, server_default=""),
)

# ---------------------------------------------------------------------------
# Groep 3a — Leveranciersproducten (nieuw model: identiteit + SCD2-tarieven)
# ---------------------------------------------------------------------------

vtest_scrape_run = sa.Table(
    "vtest_scrape_run",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("version_id", sa.String(26), sa.ForeignKey("data_version.version_id"), nullable=False),
    sa.Column("scraped_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("postcode", sa.String(10), nullable=True),
    sa.Column("browser", sa.Text, nullable=True),
    sa.Column("headless", sa.Boolean, nullable=True),
    sa.Column("products_found", sa.Integer, nullable=True),
    sa.Column("dump_bestand", sa.Text, nullable=True),
)

leverancier = sa.Table(
    "leverancier",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("naam", sa.Text, unique=True, nullable=False),
    sa.Column("website_url", sa.Text, nullable=True),
    sa.Column("klantendienst_telefoon", sa.Text, nullable=True),
    sa.Column("klantendienst_email", sa.Text, nullable=True),
    sa.Column("vreg_service_score", sa.Numeric(3, 1), nullable=True),
    # "ENGIE (handelsnaam van Electrabel)" wordt naam="ENGIE",
    # juridische_entiteit="Electrabel". Het merk is de identiteit, de entiteit
    # een eigenschap: merken die dezelfde entiteit delen maar los verkocht
    # worden (de zeven merken van Energy Together) blijven aparte rijen.
    sa.Column("juridische_entiteit", sa.Text, nullable=True),
    sa.Column("bijgewerkt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    # De VREG-export spelt dezelfde leverancier niet altijd gelijk ("Dots
    # Energy" naast "Dots energy"). Zonder deze index krijgt één leverancier
    # twee rijen en raken zijn producten over allebei verdeeld.
    sa.Index("uq_leverancier_naam_lower", sa.text("lower(naam)"), unique=True),
)

energie_product = sa.Table(
    "energie_product",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("leverancier_id", sa.Integer, sa.ForeignKey("leverancier.id", ondelete="CASCADE"), nullable=False),
    sa.Column("vreg_id", sa.Text, unique=True, nullable=True),
    sa.Column("product_naam", sa.Text, nullable=False),
    sa.Column("energie_type", sa.Text, nullable=False),
    sa.Column("segment", sa.Text, nullable=False),
    sa.Column("tariefkaart_url", sa.Text, nullable=True),
    sa.Column("bijzondere_voorwaarden_url", sa.Text, nullable=True),
    sa.Column("groene_stroom", sa.Boolean, nullable=True),
    sa.Column("aangemaakt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    sa.UniqueConstraint("leverancier_id", "product_naam", "energie_type", "segment", name="uq_energie_product_identiteit"),
)

# Helper factory for tariff table columns to avoid duplication
def _tarief_columns():
    return [
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("product_id", sa.BigInteger, nullable=False),
        sa.Column("meter_type", sa.Text, nullable=False),
        sa.Column("prijs_type", sa.Text, nullable=False),
        sa.Column("energieprijs_kwh", sa.Numeric(12, 6), nullable=True),
        sa.Column("vaste_vergoeding_jaar", sa.Numeric(10, 2), nullable=True),
        sa.Column("groene_stroom_kwh", sa.Numeric(12, 6), nullable=True),
        sa.Column("wkk_kwh", sa.Numeric(12, 6), nullable=True),
        sa.Column("energiebijdrage_kwh", sa.Numeric(12, 6), nullable=True),
        sa.Column("param_a", sa.Numeric(12, 6), nullable=True),
        sa.Column("param_b", sa.Numeric(12, 6), nullable=True),
        sa.Column("param_c", sa.Numeric(12, 6), nullable=True),
        sa.Column("param_d", sa.Numeric(12, 6), nullable=True),
        sa.Column("param_z", sa.Numeric(12, 6), nullable=True),
        sa.Column("index_naam_a", sa.Text, nullable=True),
        sa.Column("index_naam_b", sa.Text, nullable=True),
        sa.Column("index_naam_c", sa.Text, nullable=True),
        sa.Column("index_naam_d", sa.Text, nullable=True),
        sa.Column("index_waarde_a", sa.Numeric(14, 6), nullable=True),
        sa.Column("index_waarde_b", sa.Numeric(14, 6), nullable=True),
        sa.Column("index_waarde_c", sa.Numeric(14, 6), nullable=True),
        sa.Column("index_waarde_d", sa.Numeric(14, 6), nullable=True),
        sa.Column("geldig_van", sa.Date, nullable=False),
        sa.Column("geldig_tot", sa.Date, nullable=True),
        sa.Column("bron_bestand", sa.Text, nullable=True),
        sa.Column("source_row", sa.Integer, nullable=True),
    ]

tarief_afname = sa.Table(
    "tarief_afname",
    metadata,
    *_tarief_columns(),
    sa.ForeignKeyConstraint(["product_id"], ["energie_product.id"], ondelete="CASCADE"),
    # prijs_type hoort in de sleutel: hetzelfde product wordt soms zowel
    # variabel als dynamisch aangeboden, met een eigen formule per type.
    # Zonder dat onderscheid verdringen die elkaars historiek.
    sa.Index("ix_tarief_afname_open", "product_id", "meter_type", "prijs_type",
             unique=True, postgresql_where=sa.text("geldig_tot IS NULL")),
    sa.Index("ix_tarief_afname_lookup", "product_id", "geldig_van", "geldig_tot"),
)

tarief_injectie = sa.Table(
    "tarief_injectie",
    metadata,
    *_tarief_columns(),
    sa.ForeignKeyConstraint(["product_id"], ["energie_product.id"], ondelete="CASCADE"),
    # prijs_type hoort in de sleutel: hetzelfde product wordt soms zowel
    # variabel als dynamisch aangeboden, met een eigen formule per type.
    # Zonder dat onderscheid verdringen die elkaars historiek.
    sa.Index("ix_tarief_injectie_open", "product_id", "meter_type", "prijs_type",
             unique=True, postgresql_where=sa.text("geldig_tot IS NULL")),
)

# ---------------------------------------------------------------------------
# Groep 3b — Live vtest.be-scrape (contractmetadata + postcode-tarieven)
# ---------------------------------------------------------------------------

vtest_contract = sa.Table(
    "vtest_contract",
    metadata,
    sa.Column("vreg_id", sa.Text, primary_key=True),
    sa.Column("leverancier_raw", sa.Text, nullable=False),
    sa.Column("product_raw", sa.Text, nullable=False),
    sa.Column("energie_type", sa.Text, nullable=True),
    sa.Column("tarief_type", sa.Text, nullable=True),
    sa.Column("looptijd_tekst", sa.Text, nullable=True),
    sa.Column("looptijd_maanden", sa.SmallInteger, nullable=True),
    sa.Column("datum_intekenen_van", sa.Date, nullable=True),
    sa.Column("datum_intekenen_tot", sa.Date, nullable=True),
    sa.Column("datum_start_levering_van", sa.Date, nullable=True),
    sa.Column("datum_start_levering_tot", sa.Date, nullable=True),
    sa.Column("doelgroep_zonnepanelen", sa.Text, nullable=True),
    sa.Column("doelgroep_ev", sa.Text, nullable=True),
    sa.Column("doelgroep_energiedelen", sa.Text, nullable=True),
    sa.Column("doelgroep_leegstand", sa.Text, nullable=True),
    sa.Column("doelgroep_groepsaankoop", sa.Text, nullable=True),
    sa.Column("prijszekerheid_termijn", sa.Text, nullable=True),
    sa.Column("link_tariefkaart", sa.Text, nullable=True),
    sa.Column("link_voorwaarden", sa.Text, nullable=True),
    sa.Column("link_supplier", sa.Text, nullable=True),
    sa.Column("contracttype", sa.Text, nullable=True),
    sa.Column("supplier_id", sa.Text, nullable=True),
    sa.Column("product_id", sa.Text, nullable=True),
    sa.Column("green_type", sa.Text, nullable=True),
    sa.Column("stars", sa.Text, nullable=True),
    sa.Column("complex_product", sa.Boolean, nullable=True),
    sa.Column("grayedout", sa.Boolean, nullable=True),
    sa.Column("laatst_gezien_versie", sa.String(26), sa.ForeignKey("data_version.version_id"), nullable=False),
    sa.Column("laatst_gezien_op", sa.TIMESTAMP(timezone=True), nullable=False),
)

vtest_postcode_prijs = sa.Table(
    "vtest_postcode_prijs",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("vreg_id", sa.Text, sa.ForeignKey("vtest_contract.vreg_id", ondelete="CASCADE"), nullable=False),
    sa.Column("postcode", sa.String(10), nullable=False),
    sa.Column("segment", sa.Text, nullable=False),
    sa.Column("version_id", sa.String(26), sa.ForeignKey("data_version.version_id"), nullable=False),
    sa.Column("discount_eur", sa.Numeric(10, 2), nullable=True),
    sa.Column("total_excl_btw", sa.Numeric(10, 2), nullable=True),
    sa.Column("total_incl_btw", sa.Numeric(10, 2), nullable=True),
    sa.Column("btw_bedrag", sa.Numeric(10, 2), nullable=True),
    sa.Column("totaal_verbruik_kwh", sa.Numeric(10, 2), nullable=True),
    sa.Column("prijs_indicatie_eur", sa.Numeric(10, 2), nullable=True),
    sa.Column("scraped_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.UniqueConstraint("vreg_id", "postcode", "version_id", name="uq_vtest_postcode_prijs"),
)

# ---------------------------------------------------------------------------
# Groep 4 — Netbeheerdertarieven & Overheidsheffingen
# ---------------------------------------------------------------------------

netbeheerder_tarief = sa.Table(
    "netbeheerder_tarief",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("netbeheerder_code", sa.String(40), sa.ForeignKey("netbeheerder.code"), nullable=False),
    sa.Column("energie_type", sa.Text, nullable=False),
    sa.Column("contract_richting", sa.Text, nullable=False),
    sa.Column("klanttype", sa.Text, nullable=False),
    sa.Column("tarieftype", sa.Text, nullable=True),
    sa.Column("tariefdetail", sa.Text, nullable=True),
    # Dezelfde tariefnaam komt voor met verschillende eenheden — bij FA staat
    # het prosumententarief zowel als 51,54 EUR/kW/jaar als 1,8984501 zonder
    # eenheid. Zonder de notering in de sleutel gelden die als duplicaat.
    # Leeg wordt "" en niet NULL: PostgreSQL ziet NULLs in een unieke sleutel
    # als onderling verschillend, waardoor een echt dubbel er alsnog in mag.
    sa.Column("tariefnotering", sa.Text, nullable=False, server_default=""),
    sa.Column("prijs", sa.Numeric(14, 6), nullable=True),
    sa.Column("geldig_van", sa.Date, nullable=False),
    sa.Column("geldig_tot", sa.Date, nullable=True),
    sa.Column("source_sheet", sa.Text, nullable=True),
    sa.Column("source_row", sa.Integer, nullable=True),
    sa.UniqueConstraint(
        "netbeheerder_code", "energie_type", "contract_richting",
        "klanttype", "tarieftype", "tariefdetail", "tariefnotering", "geldig_van",
        name="uq_netbeheerder_tarief",
    ),
    sa.Index("ix_netbeheerder_tarief_open", "netbeheerder_code", "energie_type", "klanttype", "tarieftype", "tariefdetail", "tariefnotering",
             unique=True, postgresql_where=sa.text("geldig_tot IS NULL")),
)

overheidsheffing_accijns_schijf = sa.Table(
    "overheidsheffing_accijns_schijf",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("energievorm", sa.Text, nullable=False),
    sa.Column("klantcategorie", sa.Text, nullable=False),
    sa.Column("van_mwh", sa.Numeric(12, 3), nullable=False),
    sa.Column("tot_mwh", sa.Numeric(12, 3), nullable=True),
    sa.Column("accijns_eur_mwh", sa.Numeric(10, 4), nullable=False),
    sa.Column("bijzondere_accijns_eur_mwh", sa.Numeric(10, 4), nullable=False),
    sa.Column("energiebijdrage_eur_mwh", sa.Numeric(10, 4), nullable=False),
    # De accijns is een reeks regimes met een ingangsdatum, geen vast bedrag:
    # gezinnen gingen op 01/08/2026 van 47,4811 naar 46,00 EUR/MWh, terwijl
    # ondernemingen sinds 2022 op 14,21 staan. Zonder deze kolom slaat de
    # tabel die regimes plat tot één antwoord voor alle jaren.
    sa.Column("geldig_vanaf", sa.Date, nullable=False),
    # False = uit een secundaire bron overgenomen en nog niet tegen vtest.be
    # of een officiële publicatie gelegd.
    sa.Column("geverifieerd", sa.Boolean, nullable=False, server_default="false"),
    sa.Column("bron", sa.Text, nullable=False),
    sa.UniqueConstraint(
        "energievorm", "klantcategorie", "van_mwh", "geldig_vanaf",
        name="uq_overheidsheffing_accijns_schijf",
    ),
)

overheidsheffing_energiefonds = sa.Table(
    "overheidsheffing_energiefonds",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("jaar", sa.SmallInteger, nullable=False),
    sa.Column("spanningsniveau", sa.Text, nullable=False),
    sa.Column("klantcategorie", sa.Text, nullable=False, server_default=""),
    sa.Column("eur_per_maand", sa.Numeric(10, 2), nullable=False),
    sa.Column("bron", sa.Text, nullable=False),
    sa.UniqueConstraint("jaar", "spanningsniveau", "klantcategorie", name="uq_overheidsheffing_energiefonds"),
)

# Vervoerstarief van Fluxys: de doorrekening van het vervoersnet op een
# distributienetaansluiting. Staat in geen VREG-werkboek — die dekken alleen
# de distributie — en ontbrak daardoor volledig, wat elke gasfactuur ongeveer
# 25 EUR per jaar te laag maakte.
nettarief_transport = sa.Table(
    "nettarief_transport",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("energievorm", sa.Text, nullable=False),
    sa.Column("klantcategorie", sa.Text, nullable=False),
    sa.Column("eur_per_kwh", sa.Numeric(12, 8), nullable=False),
    sa.Column("geldig_vanaf", sa.Date, nullable=False),
    sa.Column("geverifieerd", sa.Boolean, nullable=False, server_default="false"),
    sa.Column("bron", sa.Text, nullable=False),
    sa.UniqueConstraint(
        "energievorm", "klantcategorie", "geldig_vanaf",
        name="uq_nettarief_transport",
    ),
)

overheidsheffing_btw = sa.Table(
    "overheidsheffing_btw",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("component", sa.Text, nullable=False),
    sa.Column("percentage", sa.Numeric(5, 4), nullable=False),
    sa.Column("vrijgesteld", sa.Boolean, nullable=False, server_default="false"),
    sa.Column("geldig_vanaf", sa.Date, nullable=False),
    sa.Column("bron", sa.Text, nullable=False),
    sa.UniqueConstraint("component", "geldig_vanaf", name="uq_overheidsheffing_btw"),
)

# ---------------------------------------------------------------------------
# Groep 5 — Marktcurves (scaffold)
# ---------------------------------------------------------------------------

marktcurve = sa.Table(
    "marktcurve",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("version_id", sa.String(26), sa.ForeignKey("data_version.version_id"), nullable=False),
    sa.Column("curve_type", sa.Text, nullable=False),
    sa.Column("energie_type", sa.Text, nullable=True),
    sa.Column("groep", sa.Text, nullable=True),
    sa.Column("parameter", sa.Text, nullable=True),
    sa.Column("datum", sa.Date, nullable=True),
    sa.Column("tijdstip", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("waarde", sa.Numeric(14, 6), nullable=True),
    sa.Column("source_sheet", sa.Text, nullable=True),
)

# ---------------------------------------------------------------------------
# Groep 6 — Toekomstige tabellen (scaffold, leeg)
# ---------------------------------------------------------------------------

gebruiker = sa.Table(
    "gebruiker",
    metadata,
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
    sa.Column("geschatte_maandpiek_kw", sa.Numeric(6, 2), server_default="2.5"),
    sa.Column("huidig_leverancier", sa.Text, nullable=True),
    sa.Column("huidig_product", sa.Text, nullable=True),
    sa.Column("contract_startdatum", sa.Date, nullable=True),
    sa.Column("aangemaakt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    sa.Column("bijgewerkt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
)

meterinterval = sa.Table(
    "meterinterval",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("gebruiker_id", sa.Integer, sa.ForeignKey("gebruiker.id"), nullable=False),
    sa.Column("tijdstip", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("afname_kwh", sa.Numeric(8, 4), nullable=False, server_default="0"),
    sa.Column("injectie_kwh", sa.Numeric(8, 4), nullable=False, server_default="0"),
    sa.Column("bron_bestand", sa.Text, nullable=True),
    sa.Column("aangemaakt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    sa.UniqueConstraint("gebruiker_id", "tijdstip", name="uq_meterinterval_gebruiker_tijdstip"),
)

simulatie = sa.Table(
    "simulatie",
    metadata,
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
