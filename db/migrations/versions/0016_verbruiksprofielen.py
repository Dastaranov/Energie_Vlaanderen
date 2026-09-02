"""Verbruiksprofielen (Synergrid: SLP-EX, RLP0N, SPP) als databanktabel.

De ingest-pipeline (`ingest/profielen/`) parseert de jaarlijkse
Synergrid-werkboeken naar staging-CSV's; deze migratie geeft ze een
bestemming in de databank zodat ze bruikbaar worden voor simulaties
(schatten van een jaarverbruik per kwartier/uur, zie `docs/manifest.md`
§4.4/§9).

Twee wijzigingen:

1. `netbeheerder.gln` — Synergrid identificeert netbeheerders met een GLN
   (Global Location Number), niet met de namen die de rest van deze
   applicatie gebruikt (`DNB_CODES`). De kolom is nullable: de 8 bestaande
   Vlaamse Fluvius-rijen + Enexis dragen er geen, enkel wat via de
   profielenimport bijkomt (ook de Waalse/Brusselse netbeheerders die
   Synergrid meelevert — RLP0N is een Belgisch, geen Vlaams profiel).

2. `verbruiksprofiel_waarde` — één rij per (profiel_type, energie_type,
   jaar, netbeheerder, tijdstip). Bewust geen SCD2 (Synergrid vervangt een
   jaarprofiel in zijn geheel, het wijzigt niet binnen het jaar) en bewust
   `Float` in plaats van `Numeric`: dit zijn geen geldbedragen maar
   statistische profielgewichten tot 16 decimalen nauwkeurig — zie de
   toelichting in schema.py. `energie_type` en `netbeheerder_code` zijn
   `NOT NULL DEFAULT ''` in plaats van nullable, net als
   `netbeheerder_tarief.tariefnotering`: NULL in een unieke sleutel is voor
   PostgreSQL nooit gelijk aan een andere NULL, wat de ON CONFLICT-upsert
   van de nationale profielen (SLP-EX, RLP0N-gas, SPP) zou breken.
   `netbeheerder_code=''` vereist een gezaaide sentinelrij in
   `netbeheerder` (code=''), die deze migratie meteen aanmaakt.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-02 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "netbeheerder",
        sa.Column("gln", sa.String(length=20), nullable=True),
    )
    op.create_unique_constraint("uq_netbeheerder_gln", "netbeheerder", ["gln"])

    # Sentinelrij voor "geen netbeheerder van toepassing" (de nationale
    # profielen). Bestaat vóór verbruiksprofiel_waarde aangemaakt wordt,
    # zodat de FK meteen voldaan is.
    op.execute(
        "INSERT INTO netbeheerder (code, naam) VALUES ('', '(nationaal, geen netbeheerder)') "
        "ON CONFLICT (code) DO NOTHING"
    )

    op.create_table(
        "verbruiksprofiel_waarde",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("version_id", sa.String(length=26), nullable=False),
        sa.Column("profiel_type", sa.Text(), nullable=False),
        sa.Column("energie_type", sa.Text(), nullable=False, server_default=""),
        sa.Column("jaar", sa.SmallInteger(), nullable=False),
        sa.Column(
            "netbeheerder_code", sa.String(length=40), nullable=False, server_default="",
        ),
        sa.Column("tijdstip", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("waarde", sa.Float(53), nullable=True),
        sa.Column("bron_bestand", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["version_id"], ["data_version.version_id"]),
        sa.ForeignKeyConstraint(["netbeheerder_code"], ["netbeheerder.code"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profiel_type", "energie_type", "jaar", "netbeheerder_code", "tijdstip",
            name="uq_verbruiksprofiel_waarde",
        ),
    )
    op.create_index(
        "ix_verbruiksprofiel_waarde_lookup",
        "verbruiksprofiel_waarde",
        ["profiel_type", "jaar", "netbeheerder_code"],
    )


def downgrade() -> None:
    op.drop_index("ix_verbruiksprofiel_waarde_lookup", table_name="verbruiksprofiel_waarde")
    op.drop_table("verbruiksprofiel_waarde")
    op.execute("DELETE FROM netbeheerder WHERE code = ''")
    op.drop_constraint("uq_netbeheerder_gln", "netbeheerder", type_="unique")
    op.drop_column("netbeheerder", "gln")
