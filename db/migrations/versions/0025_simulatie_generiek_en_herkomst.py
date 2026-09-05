"""Maak `simulatie` generiek, en voeg herkomst toe: databankversie, code-commit, dossiersnapshot.

`simulatie` (migratie 0017) was gebouwd voor één leverancier/product per rij,
met `simulatie_regel` als kind voor de deelperiodes — de vorm van de oude
`simulatie`-mini-API. Niets schreef er ooit naartoe:
`GebruikersRepository.bewaar_simulatie()` werd door geen enkel scenario of
CLI-commando aangeroepen, en `scenario.opslag.sla_op()` (JSON/YAML) draaide
enkel op aanvraag, nooit automatisch. Beide tabellen zijn dus leeg en dit is
een vervanging, geen omvorming — er is geen rij om te bewaren.

De aanleiding: `energie_vlaanderen.scenario` omvat vandaag
`BatterijScenario`/`AnderContractScenario`/`ZonnepaneelScenario`/... en de
258-kandidaten-vergelijking van `scenario.optimaliseer`. Geen van die vormen
past nog in "één leverancier, één product, één reeks deelperiodes" — een
`BatterijScenario` heeft geen leverancier, en een optimalisatie heeft er
honderden tegelijk.

Expliciet gevraagd (niet afgeleid): een simulatie moet later **exact
reproduceerbaar** zijn — met welke databankversie, welke code-commit en welk
dossier is dit tot stand gekomen — én simulaties moeten **snel vergelijkbaar**
zijn tussen gebruikers, zonder de kwartierdata zelf te herhalen. Vandaar:

- `data_version_id` + `code_commit`/`code_dirty` + `dossier_hash`/
  `dossier_snapshot` samen bepalen ondubbelzinnig de herkomst
  (`scenario.herkomst`). `dossier_snapshot` bevat geen `Persoonsgegevens` en
  geen EAN-code — Manifest §5.2/§5.3 noemt beide expliciet gevoelig, en geen
  van beide is nodig om de berekening zelf na te rekenen.
- `scenario_type`/`scenario_naam`/`scenario_parameters` vervangen
  `aansluitingspunt_id`/`vreg_id`/`leverancier`/`product`: een scenario is nu
  vrije tekst plus zijn eigen constructor-argumenten, geen vaste kolomset.
- `resultaat` (JSON) draagt het volledige scenarioresultaat — voor een
  optimalisatie alle doorgerekende kandidaten, niet enkel de winnaar. "Data is
  macht": liever te veel bewaard dan een herberekening nodig voor het detail.
- Vier kolommen (`verschil_eur`, `beste_leverancier`, `beste_product`,
  `beste_contracttype`) staan naast dat JSON-veld met opzet als eigen kolom:
  dat is precies waarop "snelle vergelijkingen tussen gebruikers" filtert en
  sorteert, en JSON-velden zijn daar traag op te doorzoeken.

`simulatie_regel` vervalt zonder vervanging: het detail per deelperiode zit nu
in `resultaat`, en niets las de tabel ooit.
"""
from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_simulatie_regel_simulatie", table_name="simulatie_regel")
    op.drop_table("simulatie_regel")
    op.drop_table("simulatie")

    op.create_table(
        "simulatie",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("gebruiker_id", sa.Uuid, sa.ForeignKey("gebruiker.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scenario_type", sa.Text, nullable=False),
        sa.Column("scenario_naam", sa.Text, nullable=False, server_default=""),
        sa.Column("scenario_parameters", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("periode_van", sa.Date, nullable=False),
        sa.Column("periode_tot", sa.Date, nullable=False),
        sa.Column("data_version_id", sa.String(26), sa.ForeignKey("data_version.version_id"), nullable=True),
        sa.Column("code_commit", sa.String(40), nullable=True),
        sa.Column("code_dirty", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("dossier_hash", sa.String(64), nullable=False),
        sa.Column("dossier_snapshot", sa.JSON, nullable=False),
        sa.Column("basislijn_totaal_eur", sa.Numeric(14, 2), nullable=True),
        sa.Column("scenario_totaal_eur", sa.Numeric(14, 2), nullable=True),
        sa.Column("verschil_eur", sa.Numeric(14, 2), nullable=True),
        sa.Column("beste_leverancier", sa.Text, nullable=True),
        sa.Column("beste_product", sa.Text, nullable=True),
        sa.Column("beste_contracttype", sa.Text, nullable=True),
        sa.Column("exactheidsklasse", sa.Text, nullable=False, server_default="geschat"),
        sa.Column("resultaat", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("aannames", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("warnings", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("aangemaakt_op", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_simulatie_gebruiker", "simulatie", ["gebruiker_id", "aangemaakt_op"])
    op.create_index("ix_simulatie_vergelijking", "simulatie", ["scenario_type", "verschil_eur"])
    op.create_index("ix_simulatie_dossier_hash", "simulatie", ["dossier_hash"])


def downgrade() -> None:
    """Terugdraaien verliest de herkomst- en resultaatvelden onherroepelijk —
    aanvaardbaar, want beide tabellen zijn en blijven leeg (zie de
    moduledocstring): er is nooit een rij geweest om te bewaren."""
    op.drop_index("ix_simulatie_dossier_hash", table_name="simulatie")
    op.drop_index("ix_simulatie_vergelijking", table_name="simulatie")
    op.drop_index("ix_simulatie_gebruiker", table_name="simulatie")
    op.drop_table("simulatie")

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
