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
    # GLN (Global Location Number): de identifier waarmee Synergrid
    # netbeheerders in de verbruiksprofielen (SLP-EX/RLP0N/SPP) aanduidt.
    # Nullable — de oorspronkelijke 8 Vlaamse Fluvius-DNB's + Enexis werden
    # nooit met een GLN gezaaid, enkel de netbeheerders die via de
    # profielenimport bijkomen dragen er standaard één.
    sa.Column("gln", sa.String(20), nullable=True, unique=True),
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
    # vtest.be onderscheidt GREEN van GREENLOCAL (lokaal opgewekt). Dat
    # verschil telt voor een vergelijker; een boolean alleen zou het
    # gelijkschakelen. Komt uit de live scrape, dus enkel gevuld voor
    # producten die via vreg_id gekoppeld zijn.
    sa.Column("groene_stroom_type", sa.Text, nullable=True),
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
        # Zes decimalen zoals de andere prijskolommen (migratie 0022). Met
        # Numeric(10, 2) werd 61,321 stil 61,32 — een afronding van brondata
        # die de cel-voor-cel-audit tegen het werkboek onmogelijk maakte.
        sa.Column("vaste_vergoeding_jaar", sa.Numeric(12, 6), nullable=True),
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

# SCD2 op de scrapedatum (migratie 0019). `geldig_van` zegt vanaf wanneer deze
# metadata bij vtest.be zo stond — een eigenschap van de bron. Wanneer wij die
# gegevens publiceerden staat apart in `gepubliceerd_op` en kan er dagen na
# liggen; die twee door elkaar halen zou de historiek de administratie laten
# volgen in plaats van de werkelijkheid.
#
# Let op: deze tabel draagt nu vier datumfamilies naast elkaar. Ze betekenen
# elk iets anders en schuiven onafhankelijk:
#   - datum_intekenen_*        : wanneer je op dit contract kunt intekenen
#   - datum_start_levering_*   : wanneer de levering kan starten
#   - geldig_van / geldig_tot  : wanneer deze *beschrijving* van het contract gold
#   - gepubliceerd_op          : wanneer wij die beschrijving publiceerden
vtest_contract = sa.Table(
    "vtest_contract",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("vreg_id", sa.Text, nullable=False),
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
    # De tijdas: de scrapedatum vanaf wanneer dit snapshot gold.
    sa.Column("geldig_van", sa.Date, nullable=False),
    sa.Column("geldig_tot", sa.Date, nullable=True),
    # Gezet bij het activeren van de versie (`version publish`), niet bij de
    # import: een versie die wel ingelezen maar nog niet gepubliceerd is,
    # hoort hier NULL te dragen.
    sa.Column("gepubliceerd_op", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.UniqueConstraint("vreg_id", "geldig_van", name="uq_vtest_contract_versie"),
    sa.Index("ix_vtest_contract_vreg_id", "vreg_id"),
)

vtest_postcode_prijs = sa.Table(
    "vtest_postcode_prijs",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    # Geen foreign key meer naar vtest_contract.vreg_id: die kolom is sinds
    # migratie 0019 niet meer uniek (SCD2). Beide tabellen worden in dezelfde
    # transactie uit hetzelfde CSV geschreven, dus wezen zijn uitgesloten.
    sa.Column("vreg_id", sa.Text, nullable=False),
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
    # Zeven decimalen, niet zes: VREG publiceert de nettarieven zo, en 186 van
    # de 272 gasrijen en 513 van de 776 elektriciteitsrijen dragen er ook echt
    # zeven. Op `Numeric(14, 6)` werd 0,0230382 stil 0,023038 (migratie 0024).
    sa.Column("prijs", sa.Numeric(15, 7), nullable=True),
    sa.Column("geldig_van", sa.Date, nullable=False),
    sa.Column("geldig_tot", sa.Date, nullable=True),
    sa.Column("source_sheet", sa.Text, nullable=True),
    sa.Column("source_row", sa.Integer, nullable=True),
    # Uit welke bronversie deze rij komt (migratie 0021). `source_sheet`/
    # `source_row` zeggen wáár in een werkboek, niet uit wélk werkboek. Met
    # meerdere tariefjaren naast elkaar — en zeker met een jaargang die buiten
    # de publicatieketen bijgeladen is — is dat het verschil tussen data die
    # klopt en data die herbouwbaar is.
    sa.Column("bron_versie", sa.String(26), nullable=True),
    sa.UniqueConstraint(
        "netbeheerder_code", "energie_type", "contract_richting",
        "klanttype", "tarieftype", "tariefdetail", "tariefnotering", "geldig_van",
        name="uq_netbeheerder_tarief",
    ),
    # Geen partiële index op open rijen meer: een tariefjaar wordt afgesloten
    # op 31 december (inclusief — zie migratie 0018), dus er zijn geen rijen
    # met geldig_tot IS NULL. `uq_netbeheerder_tarief` hierboven dekt de
    # uniciteit volledig: de sleutel plus geldig_van.
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
# Groep 4b — Verbruiksprofielen (Synergrid: SLP-EX, RLP0N, SPP)
# ---------------------------------------------------------------------------

# Bewust geen Numeric en geen SCD2. Numeric(14,6) (zoals marktcurve
# hieronder) zou de brondata stilzwijgend afronden: een SLP-EX-gewicht als
# 0,0002049609 heeft 10 decimalen, een SPP-waarde tot 16. "Decimal only for
# financial values — never float" (zie CLAUDE.md) is hier niet van
# toepassing: dit zijn geen geldbedragen maar statistische profielgewichten
# en productiefracties, waarvoor IEEE double precision (~15-17 significante
# cijfers) exact genoeg is en geen kunstmatige afronding invoert. Geen
# SCD2 (geldig_van/geldig_tot): Synergrid publiceert één keer per jaar een
# volledig nieuw profiel, geen wijzigingshistoriek binnen een jaar — een
# jaar/profieltype-combinatie wordt bij een herimport in zijn geheel
# vervangen (ON CONFLICT DO UPDATE op de unieke sleutel), niet aangevuld.
verbruiksprofiel_waarde = sa.Table(
    "verbruiksprofiel_waarde",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("version_id", sa.String(26), sa.ForeignKey("data_version.version_id"), nullable=False),
    # "slp_ex" | "rlp0n" | "spp"
    sa.Column("profiel_type", sa.Text, nullable=False),
    # "elektriciteit" | "gas" | "" (SPP en SLP-EX kennen geen aparte
    # energievorm — SLP-EX is per definitie elektriciteit-only, maar dat
    # apart vastleggen voegt niets toe zolang er geen gas-SLP bestaat).
    # Leeg, niet NULL: zie de toelichting bij netbeheerder_code hieronder,
    # dezelfde reden geldt hier.
    sa.Column("energie_type", sa.Text, nullable=False, server_default=""),
    sa.Column("jaar", sa.SmallInteger, nullable=False),
    # Leeg ("") voor de nationale profielen (SLP-EX, RLP0N-gas via GOS, SPP
    # ex-ante); gevuld voor RLP0N-elektriciteit, dat per netbeheerder
    # gepubliceerd wordt. Net als bij `netbeheerder_tarief.tariefnotering`
    # (zie de toelichting daar) is dit bewust geen NULL: PostgreSQL
    # behandelt NULLs in een unieke sleutel als onderling verschillend,
    # zodat elke nieuwe import van een nationaal profiel zijn 35.040 rijen
    # gewoon zou bíjvoegen in plaats van de vorige import te vervangen via
    # ON CONFLICT. Een lege string is voor de databank een gewone,
    # vergelijkbare waarde en laat de upsert wél werken. De FK vereist
    # daarom een gezaaide netbeheerder-rij met code="" (zie
    # `import_verbruiksprofielen` in importer.py) — geen losse partiële
    # index, om precies dezelfde reden als bij tariefnotering.
    sa.Column(
        "netbeheerder_code", sa.String(40), sa.ForeignKey("netbeheerder.code"),
        nullable=False, server_default="",
    ),
    sa.Column("tijdstip", sa.TIMESTAMP(timezone=True), nullable=False),
    # Float(53) i.p.v. kaal Float: PostgreSQL leest een ongequalificeerde
    # FLOAT weliswaar al als double precision (float8), maar 53 bits
    # precisie hier expliciet vastleggen laat geen twijfel bestaan — dit is
    # exact de kolom waarvoor de precisie is uitgemeten (16 decimalen bij
    # SPP, zie hierboven).
    sa.Column("waarde", sa.Float(53), nullable=True),
    sa.Column("bron_bestand", sa.Text, nullable=True),
    sa.UniqueConstraint(
        "profiel_type", "energie_type", "jaar", "netbeheerder_code", "tijdstip",
        name="uq_verbruiksprofiel_waarde",
    ),
    sa.Index(
        "ix_verbruiksprofiel_waarde_lookup",
        "profiel_type", "jaar", "netbeheerder_code",
    ),
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
# Groep 6 — Gebruikersbasis
# ---------------------------------------------------------------------------
#
# Deze groep verving in migratie 0017 een leeg scaffold (`gebruiker`,
# `meterinterval`, `simulatie`) dat sinds 0001 bestond maar door geen enkele
# importer aangeraakt werd. Het oude `gebruiker` was één platte spiegel van
# `domain.Profile`: één metertype, één contract als drie tekstkolommen, geen
# EAN en geen tweede energiedrager. Wat daar niet in paste:
#
# - Een EAN identificeert één toegangspunt voor één energiedrager. Elektriciteit
#   en gas zijn aparte EAN's, dus aparte rijen in `aansluitingspunt`. Injectie is
#   géén aparte EAN maar een aparte registerlezing.
# - Een leveringscontract heeft een geldigheidsperiode, en er zijn er meerdere na
#   elkaar. Drie kolommen op de gebruiker kunnen dat niet dragen.
# - Persoonsgegevens horen apart van rekenkundige gegevens (Manifest §4.3/§5.1),
#   omdat login en API het doel zijn en achteraf scheiden veel duurder is.
#
# Geldigheidsperiodes zijn half-open [geldig_van, geldig_tot); `geldig_tot IS
# NULL` betekent "nog lopend". Half-open omdat contracten en tariefregimes op
# dezelfde dag opvolgen — een inclusieve einddatum zou die dag dubbel tellen.

gebruiker = sa.Table(
    "gebruiker",
    metadata,
    # UUID en geen autoincrement: het id verlaat straks dit systeem (API, export)
    # en mag dan niet verraden hoeveel gebruikers er zijn of wie eerder kwam.
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("segment", sa.Text, nullable=False, server_default="Woning"),
    sa.Column("land", sa.String(2), nullable=False, server_default="BE"),
    sa.Column("toestemming_referentie", sa.Text, nullable=True),
    sa.Column("aangemaakt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    sa.Column("bijgewerkt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
)

# Apart van `gebruiker`, niet als extra kolommen erop: zo kan een rapport of een
# API-antwoord over verbruik en kosten gebouwd worden zonder deze tabel ooit aan
# te raken, en is "verwijder mijn persoonsgegevens" één DELETE.
gebruiker_persoonsgegeven = sa.Table(
    "gebruiker_persoonsgegeven",
    metadata,
    sa.Column("gebruiker_id", sa.Uuid, sa.ForeignKey("gebruiker.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("naam", sa.Text, nullable=False, server_default=""),
    sa.Column("email", sa.Text, nullable=False, server_default=""),
    sa.Column("straat", sa.Text, nullable=False, server_default=""),
    sa.Column("huisnummer", sa.Text, nullable=False, server_default=""),
    sa.Column("postcode", sa.String(10), nullable=False, server_default=""),
    sa.Column("gemeente", sa.Text, nullable=False, server_default=""),
    sa.Column("bijgewerkt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
)

aansluitingspunt = sa.Table(
    "aansluitingspunt",
    metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("gebruiker_id", sa.Uuid, sa.ForeignKey("gebruiker.id", ondelete="CASCADE"), nullable=False),
    sa.Column("energie_type", sa.Text, nullable=False),
    # Manifest §5.2: gevoelig. Nullable omdat veel gebruikers hun EAN niet kennen
    # en de berekening hem niet nodig heeft — postcode volstaat voor
    # tariefselectie. Uniek zodat hetzelfde toegangspunt niet twee keer
    # geregistreerd raakt.
    sa.Column("ean_code", sa.String(18), nullable=True, unique=True),
    sa.Column("postcode", sa.String(10), sa.ForeignKey("gemeente.postcode"), nullable=False),
    sa.Column("gemeente_naam", sa.Text, nullable=False, server_default=""),
    sa.Column("netbeheerder_code", sa.String(40), sa.ForeignKey("netbeheerder.code"), nullable=True),
    sa.Column("spanningsniveau", sa.Text, nullable=False, server_default="laag"),
    # Het fysieke aansluitingsvermogen — niet te verwarren met de AC-limiet van
    # de omvormer (`installatie_asset.omvormer_kva`) of met de maandpiek van het
    # capaciteitstarief (`meter`). Drie verschillende getallen.
    sa.Column("aansluitingsvermogen_kva", sa.Numeric(9, 3), nullable=True),
    sa.Column("aantal_fasen", sa.SmallInteger, nullable=True),
    sa.Column("geldig_van", sa.Date, nullable=True),
    sa.Column("geldig_tot", sa.Date, nullable=True),
    sa.Column("aangemaakt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    sa.Index("ix_aansluitingspunt_gebruiker", "gebruiker_id", "energie_type"),
)

meter = sa.Table(
    "meter",
    metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("aansluitingspunt_id", sa.Uuid, sa.ForeignKey("aansluitingspunt.id", ondelete="CASCADE"), nullable=False),
    sa.Column("meterregime", sa.Text, nullable=False, server_default="digitaal"),
    # Apart van het meterregime: een digitale meter kan enkelvoudig of tweevoudig
    # geregistreerd zijn, en 'exclusief nacht' is een derde register met een
    # eigen nettarief.
    sa.Column("registerschema", sa.Text, nullable=False, server_default="enkelvoudig"),
    # Alleen een klassieke terugdraaiende meter mét PV valt onder het
    # prosumententarief; een digitale meter met PV niet. Dat verschil loopt in de
    # honderden euro's per jaar, dus het is een eigen kolom en geen afleiding.
    sa.Column("terugdraaiend", sa.Boolean, nullable=False, server_default="false"),
    # Numeric(7, 3), niet (6, 2): de vtest-standaardpiek is 4,218 kW en zou op
    # twee decimalen stil 4,22 worden. Deze twee stonden in migratie 0015 op
    # `gebruiker`; ze horen bij de meter, want de ondergrens van 2,5 kW hangt aan
    # het meetregime en niet aan hoeveel er verbruikt is.
    sa.Column("geschatte_maandpiek_kw", sa.Numeric(7, 3), nullable=False, server_default="4.218"),
    sa.Column("minimum_maandpiek_kw", sa.Numeric(7, 3), nullable=False, server_default="2.5"),
    sa.Column("geldig_van", sa.Date, nullable=True),
    sa.Column("geldig_tot", sa.Date, nullable=True),
    sa.Index("ix_meter_aansluitingspunt", "aansluitingspunt_id"),
)

installatie_asset = sa.Table(
    "installatie_asset",
    metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("aansluitingspunt_id", sa.Uuid, sa.ForeignKey("aansluitingspunt.id", ondelete="CASCADE"), nullable=False),
    sa.Column("type", sa.Text, nullable=False),
    # merk/model sluiten aan op de sleutel (merk, model) van
    # hardware.BatterijRepository en hardware.OmvormerRepository, zodat een asset
    # naar een nameplate-specificatie mét bronvermelding wijst.
    sa.Column("merk", sa.Text, nullable=False, server_default=""),
    sa.Column("model", sa.Text, nullable=False, server_default=""),
    sa.Column("kwp", sa.Numeric(9, 3), nullable=True),
    sa.Column("omvormer_merk", sa.Text, nullable=False, server_default=""),
    sa.Column("omvormer_model", sa.Text, nullable=False, server_default=""),
    sa.Column("omvormer_kva", sa.Numeric(9, 3), nullable=True),
    # AC- of DC-gekoppeld bepaalt of PV de batterij kan laden zonder de meter te
    # passeren — een modeldimensie, geen detail.
    sa.Column("topologie", sa.Text, nullable=True),
    sa.Column("geldig_van", sa.Date, nullable=True),
    sa.Column("geldig_tot", sa.Date, nullable=True),
    sa.Index("ix_installatie_asset_aansluitingspunt", "aansluitingspunt_id", "type"),
)

leveringscontract = sa.Table(
    "leveringscontract",
    metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("aansluitingspunt_id", sa.Uuid, sa.ForeignKey("aansluitingspunt.id", ondelete="CASCADE"), nullable=False),
    sa.Column("leverancier", sa.Text, nullable=False),
    sa.Column("product", sa.Text, nullable=False, server_default=""),
    sa.Column("vreg_id", sa.Text, nullable=True),
    # "vast" | "variabel" | "dynamisch" | "tou". Niet te verwarren met
    # `netbeheerder_tarief.contract_richting`, dat "Afname"/"Injectie" bevat.
    sa.Column("contracttype", sa.Text, nullable=False),
    sa.Column("geldig_van", sa.Date, nullable=False),
    sa.Column("geldig_tot", sa.Date, nullable=True),
    # De kern van een correcte historische kost: een vast contract volgt de
    # actuele tariefkaart niet, de prijs bevriest bij ondertekening. Zonder deze
    # datum koppelt een terugblik het contract aan de tariefrij van vandaag.
    sa.Column("tariefkaart_geldig_van", sa.Date, nullable=True),
    sa.Column("bron", sa.Text, nullable=False, server_default=""),
    sa.Index("ix_leveringscontract_lookup", "aansluitingspunt_id", "geldig_van", "geldig_tot"),
)

verbruiksopgave = sa.Table(
    "verbruiksopgave",
    metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("aansluitingspunt_id", sa.Uuid, sa.ForeignKey("aansluitingspunt.id", ondelete="CASCADE"), nullable=False),
    sa.Column("periode_van", sa.Date, nullable=False),
    sa.Column("periode_tot", sa.Date, nullable=False),
    sa.Column("afname_dag_kwh", sa.Numeric(12, 3), nullable=False, server_default="0"),
    sa.Column("afname_nacht_kwh", sa.Numeric(12, 3), nullable=False, server_default="0"),
    sa.Column("afname_exclusief_nacht_kwh", sa.Numeric(12, 3), nullable=False, server_default="0"),
    sa.Column("injectie_dag_kwh", sa.Numeric(12, 3), nullable=False, server_default="0"),
    sa.Column("injectie_nacht_kwh", sa.Numeric(12, 3), nullable=False, server_default="0"),
    # "meting" | "factuur" | "manueel" | "schatting" — bepaalt mee de
    # exactheidsklasse van elk bedrag dat hierop steunt.
    sa.Column("bron", sa.Text, nullable=False, server_default="manueel"),
    sa.Column("dekkingsgraad", sa.Numeric(5, 4), nullable=False, server_default="1"),
    sa.Column("aannames", sa.JSON, nullable=False, server_default="[]"),
    sa.UniqueConstraint(
        "aansluitingspunt_id", "periode_van", "periode_tot", "bron",
        name="uq_verbruiksopgave_periode",
    ),
)

toestemming = sa.Table(
    "toestemming",
    metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("gebruiker_id", sa.Uuid, sa.ForeignKey("gebruiker.id", ondelete="CASCADE"), nullable=False),
    sa.Column("doel", sa.Text, nullable=False),
    sa.Column("verleend_op", sa.Date, nullable=False),
    sa.Column("ingetrokken_op", sa.Date, nullable=True),
    sa.Column("bron", sa.Text, nullable=False, server_default=""),
    sa.Index("ix_toestemming_gebruiker", "gebruiker_id", "doel"),
)

meterinterval = sa.Table(
    "meterinterval",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    # Hing aan `gebruiker_id`; een meting hoort bij een toegangspunt (EAN), niet
    # bij een persoon. Een gebruiker met elektriciteit én gas had anders twee
    # reeksen in dezelfde tabel zonder onderscheid.
    sa.Column("aansluitingspunt_id", sa.Uuid, sa.ForeignKey("aansluitingspunt.id", ondelete="CASCADE"), nullable=False),
    sa.Column("tijdstip", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("afname_kwh", sa.Numeric(12, 4), nullable=False, server_default="0"),
    sa.Column("injectie_kwh", sa.Numeric(12, 4), nullable=False, server_default="0"),
    # Manifest §5.4 `quality_code`: NOT NULL DEFAULT '' en niet nullable, zodat de
    # kolom in een ON CONFLICT-sleutel kan (NULL is in Postgres niet gelijk aan
    # NULL — zelfde reden als netbeheerder_tarief.tariefnotering).
    sa.Column("kwaliteitscode", sa.Text, nullable=False, server_default=""),
    sa.Column("bron_bestand", sa.Text, nullable=True),
    sa.Column("aangemaakt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    sa.UniqueConstraint("aansluitingspunt_id", "tijdstip", name="uq_meterinterval_punt_tijdstip"),
)

simulatie = sa.Table(
    "simulatie",
    metadata,
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
    # Manifest §5.8: zonder deze drie is een bedrag niet te beoordelen — was het
    # gemeten, gereconstrueerd of geschat, waarop steunde het, en wat is er
    # ingevuld dat de gebruiker niet aangeleverd heeft.
    sa.Column("exactheidsklasse", sa.Text, nullable=False, server_default="geschat"),
    sa.Column("bronversies", sa.JSON, nullable=False, server_default="{}"),
    sa.Column("aannames", sa.JSON, nullable=False, server_default="[]"),
    sa.Column("warnings", sa.JSON, nullable=False, server_default="[]"),
    sa.Column("aangemaakt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
)

# Eén rij per deelperiode uit `gebruikers.periodes.snijd()`. Bestaat omdat een
# jaartotaal niet uitlegt waarom het zo hoog is: een contractwissel op 01/08 en
# een accijnswissel op diezelfde dag zijn twee verschillende oorzaken, en
# `redenen` bewaart welke van beide deze knip veroorzaakte.
simulatie_regel = sa.Table(
    "simulatie_regel",
    metadata,
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
    sa.Index("ix_simulatie_regel_simulatie", "simulatie_id", "periode_van"),
)
