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
# Groep 3 — Productdata (vtest + XLSX)
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

vtest_product = sa.Table(
    "vtest_product",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("version_id", sa.String(26), sa.ForeignKey("data_version.version_id"), nullable=False),
    sa.Column("vreg_id", sa.Text, nullable=False),
    sa.Column("scraped_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("leverancier", sa.Text, nullable=False),
    sa.Column("product", sa.Text, nullable=False),
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
    sa.Column("prijs_indicatie_eur", sa.Numeric(10, 2), nullable=True),
    sa.Column("link_tariefkaart", sa.Text, nullable=True),
    sa.Column("link_voorwaarden", sa.Text, nullable=True),
    sa.Column("link_supplier", sa.Text, nullable=True),
    sa.Column("scrape_run_id", sa.BigInteger, sa.ForeignKey("vtest_scrape_run.id"), nullable=True),
    sa.UniqueConstraint("version_id", "vreg_id", name="uq_vtest_product_version_vreg"),
)

vtest_product_match = sa.Table(
    "vtest_product_match",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("version_id", sa.String(26), nullable=False),
    sa.Column("vreg_id", sa.Text, nullable=False),
    sa.Column("handelsnaam", sa.Text, nullable=True),
    sa.Column("productnaam", sa.Text, nullable=True),
    sa.Column("match_status", sa.Text, nullable=False),
    sa.Column("gekoppeld_op", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.UniqueConstraint("version_id", "vreg_id", name="uq_vtest_product_match_version_vreg"),
    sa.ForeignKeyConstraint(
        ["version_id", "vreg_id"],
        ["vtest_product.version_id", "vtest_product.vreg_id"],
        name="vtest_product_match_vtest_product_fkey",
    ),
)

leverancier_product = sa.Table(
    "leverancier_product",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("version_id", sa.String(26), sa.ForeignKey("data_version.version_id"), nullable=False),
    sa.Column("jaar", sa.SmallInteger, nullable=False),
    sa.Column("maand", sa.SmallInteger, nullable=False),
    sa.Column("segment", sa.Text, nullable=False),
    sa.Column("energie_type", sa.Text, nullable=False),
    sa.Column("contract_richting", sa.Text, nullable=False),
    sa.Column("leverancier", sa.Text, nullable=False),
    sa.Column("product", sa.Text, nullable=False),
    sa.Column("bron_type", sa.Text, nullable=False),
    sa.Column("bron_bestand", sa.Text, nullable=True),
    sa.Column("source_sheet", sa.Text, nullable=True),
    sa.UniqueConstraint(
        "version_id", "energie_type", "contract_richting", "leverancier", "product",
        "jaar", "maand", "segment",
        name="uq_leverancier_product",
    ),
    sa.Index("ix_leverancier_product_lookup", "version_id", "energie_type", "leverancier", "product", "jaar", "maand"),
)

product_component = sa.Table(
    "product_component",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("leverancier_product_id", sa.BigInteger, sa.ForeignKey("leverancier_product.id"), nullable=False),
    sa.Column("component_code", sa.Text, nullable=False),
    sa.Column("component_label", sa.Text, nullable=True),
    sa.Column("eenheid", sa.Text, nullable=True),
    sa.Column("btw_code", sa.Text, nullable=True),
    sa.Column("prijs", sa.Numeric(14, 6), nullable=True),
    # Formule-coëfficiënten (NULL voor 'vast')
    sa.Column("a", sa.Numeric(12, 6), nullable=True),
    sa.Column("b", sa.Numeric(12, 6), nullable=True),
    sa.Column("c", sa.Numeric(12, 6), nullable=True),
    sa.Column("d", sa.Numeric(12, 6), nullable=True),
    sa.Column("z", sa.Numeric(12, 6), nullable=True),
    sa.Column("index_naam_a", sa.Text, nullable=True),
    sa.Column("index_naam_b", sa.Text, nullable=True),
    sa.Column("index_naam_c", sa.Text, nullable=True),
    sa.Column("index_naam_d", sa.Text, nullable=True),
    sa.Column("index_waarde_a", sa.Numeric(14, 6), nullable=True),
    sa.Column("index_waarde_b", sa.Numeric(14, 6), nullable=True),
    sa.Column("index_waarde_c", sa.Numeric(14, 6), nullable=True),
    sa.Column("index_waarde_d", sa.Numeric(14, 6), nullable=True),
    sa.Column("source_row", sa.Integer, nullable=True),
)

# ---------------------------------------------------------------------------
# Groep 4 — Netwerktarieven
# ---------------------------------------------------------------------------

netwerk_tarief = sa.Table(
    "netwerk_tarief",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("version_id", sa.String(26), sa.ForeignKey("data_version.version_id"), nullable=False),
    sa.Column("jaar", sa.SmallInteger, nullable=True),
    sa.Column("netbeheerder_code", sa.String(40), sa.ForeignKey("netbeheerder.code"), nullable=False),
    sa.Column("energie_type", sa.Text, nullable=False),
    sa.Column("contract_richting", sa.Text, nullable=False),
    sa.Column("klanttype", sa.Text, nullable=False),
    sa.Column("tarieftype", sa.Text, nullable=True),
    sa.Column("tariefdetail", sa.Text, nullable=True),
    sa.Column("tariefnotering", sa.Text, nullable=True),
    sa.Column("prijs", sa.Numeric(14, 6), nullable=True),
    sa.Column("source_sheet", sa.Text, nullable=True),
    sa.Column("source_row", sa.Integer, nullable=True),
    sa.UniqueConstraint(
        "version_id", "netbeheerder_code", "energie_type", "contract_richting",
        "klanttype", "tarieftype", "tariefdetail", "jaar",
        name="uq_netwerk_tarief",
    ),
    sa.Index("ix_netwerk_tarief_lookup", "version_id", "netbeheerder_code", "energie_type", "klanttype"),
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
