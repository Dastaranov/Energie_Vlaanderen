"""Gastoestellen, PV-oriëntatie en gebouwkenmerken vastleggen.

Aanleiding: het dossiermodel kon een lucht-lucht warmtepomp al aan (`type_wp`
is al vrije tekst, en `Warmtepomp.verwarm()` rekent generiek met bron-/
afgiftetemperatuur — geen nieuwe fysica nodig), maar drie dingen ontbraken:

- **Een verwarmingstoestel op gas** (kachel, ketel, ...) — het dossier kende
  enkel een gasaansluitingspunt met een jaarverbruik, geen toestel-niveau.
- **PV-oriëntatie** — een installatie met meerdere strings (bv. oost/zuid/
  west) kon niet als zodanig vastgelegd worden, enkel als één totaal.
- **Gebouwkenmerken** (bebouwingstype, bewoonbare oppervlakte) — nergens.

Dit is bewust **enkel het vastleggen van de data**, niet de nieuwe fysieke
modellen die ze ooit zou voeden (oriëntatie-afhankelijke PV-productie,
gemengde warmtepomp/gas-dispatch, een gebouw-warmtevraagmodel) — zie
CLAUDE.md "Uitbreiding dossiermodel" en het plan dat aan deze migratie
voorafging. Zonder deze migratie zou die data wel in `gebruiker.toml` staan,
maar nergens landen zodra ze via `GebruikersRepository`/`ScenarioContext`
naar de databank gaat.

`AssetType` krijgt met `GASTOESTEL` een vijfde waarde (geen aparte
`GASKACHEL`/`GASKETEL`: het *doel* van het toestel is een eigenschap, geen
apart type — dezelfde redenering als `WarmtepompSpec.type_wp`). Drie nieuwe
kolommen op `installatie_asset` dekken dat en de PV-oriëntatie:
`richting` (PV-string), `vermogen_kw`/`doel` (gastoestel). Twee nieuwe
kolommen op `aansluitingspunt` dekken de gebouwkenmerken. Alle vijf zijn
optioneel/met een lege-tekst-default — een dossier zonder deze data blijft
ongewijzigd werken.
"""
from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "installatie_asset",
        sa.Column("richting", sa.Text, nullable=False, server_default=""),
    )
    op.add_column(
        "installatie_asset",
        sa.Column("vermogen_kw", sa.Numeric(9, 3), nullable=True),
    )
    op.add_column(
        "installatie_asset",
        sa.Column("doel", sa.Text, nullable=False, server_default=""),
    )
    op.add_column(
        "aansluitingspunt",
        sa.Column("bebouwingstype", sa.Text, nullable=False, server_default=""),
    )
    op.add_column(
        "aansluitingspunt",
        sa.Column("bewoonbare_oppervlakte_m2", sa.Numeric(7, 1), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("aansluitingspunt", "bewoonbare_oppervlakte_m2")
    op.drop_column("aansluitingspunt", "bebouwingstype")
    op.drop_column("installatie_asset", "doel")
    op.drop_column("installatie_asset", "vermogen_kw")
    op.drop_column("installatie_asset", "richting")
