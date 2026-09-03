"""Sluit netbeheerder_tarief af op het einde van het tariefjaar.

VREG stelt de distributienettarieven per kalenderjaar vast. `geldig_tot` stond
niettemin op NULL voor elke rij — de SCD2-betekenis "nog lopend". Daardoor gold
het tarief van 2026 formeel ook nog in 2027, en zou een berekening over dat jaar
stil met de verkeerde tarieven rekenen. Geen fout, alleen een verkeerd bedrag:
dezelfde klasse als de accijnzen die na hun laatste ingangsdatum doorrekenen.

Twee dingen die daarbij samenhangen en niet los kunnen:

1. De einddatum is **inclusief** (31 december), niet half-open (1 januari). Dat
   is de conventie die deze tabel al hanteerde: `_scd2_upsert_netbeheerder`
   sluit een voorganger af op `geldig_van - 1 dag`. De half-open conventie in de
   commentaar bij `schema.py` geldt voor de gebruikerstabellen uit migratie
   0017 — een andere familie. Een dag verschil is hier precies de stille fout
   die dit project probeert te vangen.

2. `ix_netbeheerder_tarief_open` was een unieke index over de sleutel WHERE
   `geldig_tot IS NULL`. Zodra elke rij een einddatum draagt bewaakt die niets
   meer, en erger: `_scd2_upsert_netbeheerder` zocht de huidige rij op
   `geldig_tot IS NULL`, vond niets, en viel door naar een insert die op
   `uq_netbeheerder_tarief` botste. Een herimport van dezelfde versie liep zo
   stuk met een IntegrityError. De opzoeking gaat nu op de hoogste
   `geldig_van`, en de uniciteit hangt volledig aan `uq_netbeheerder_tarief` —
   dat is de volledige sleutel plus `geldig_van` en dekt hetzelfde af.

De backfill leidt het jaar af uit `geldig_van` van de rij zelf, niet uit een
vast jaartal: er staan (of komen) meerdere tariefjaren in dezelfde tabel.
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE netbeheerder_tarief
           SET geldig_tot = make_date(EXTRACT(YEAR FROM geldig_van)::int, 12, 31)
         WHERE geldig_tot IS NULL
        """
    )
    op.drop_index("ix_netbeheerder_tarief_open", table_name="netbeheerder_tarief")


def downgrade() -> None:
    # Enkel de rijen die exact op een jaargrens afgesloten zijn weer openzetten;
    # een voorganger die middenin een jaar werd afgesloten hoort dicht te
    # blijven, anders staan er twee open rijen voor dezelfde sleutel.
    op.execute(
        """
        UPDATE netbeheerder_tarief
           SET geldig_tot = NULL
         WHERE geldig_tot = make_date(EXTRACT(YEAR FROM geldig_van)::int, 12, 31)
        """
    )
    op.create_index(
        "ix_netbeheerder_tarief_open",
        "netbeheerder_tarief",
        ["netbeheerder_code", "energie_type", "klanttype",
         "tarieftype", "tariefdetail", "tariefnotering"],
        unique=True,
        postgresql_where=sa.text("geldig_tot IS NULL"),
    )
