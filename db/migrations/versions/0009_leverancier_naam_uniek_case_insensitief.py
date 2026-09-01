"""Eén leverancier per naam, ongeacht hoofdletters.

`leverancier.naam` was uniek maar hoofdlettergevoelig. De VREG-export spelt
dezelfde leverancier niet altijd gelijk — "Dots Energy" en "Dots energy" staan
er beide in — waardoor één leverancier twee rijen kreeg en zijn producten over
allebei verdeeld raakten. De vreg_id-koppeling zoekt op `lower(naam)` en kreeg
dan twee rijen terug, wat de hele import liet klappen met een
CardinalityViolation.

De importer dedupliceert nu hoofdletterongevoelig. Deze index maakt dat een
eigenschap van de databank in plaats van een gewoonte van de code: een tweede
spelling komt er niet meer in, ook niet via een ander pad.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-31 22:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

INDEX = "uq_leverancier_naam_lower"


def upgrade() -> None:
    # Bestaande dubbels opruimen voordat de index eraan kan: houd de laagste
    # id en verhang de producten van de andere spelling(en) daarnaartoe.
    op.execute(
        sa.text(
            """
            WITH doelen AS (
                SELECT lower(naam) AS sleutel, min(id) AS behoud_id
                FROM leverancier
                GROUP BY lower(naam)
                HAVING count(*) > 1
            )
            UPDATE energie_product ep
            SET leverancier_id = d.behoud_id
            FROM leverancier l
            JOIN doelen d ON lower(l.naam) = d.sleutel
            WHERE ep.leverancier_id = l.id
              AND l.id <> d.behoud_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM leverancier l
            USING (
                SELECT lower(naam) AS sleutel, min(id) AS behoud_id
                FROM leverancier
                GROUP BY lower(naam)
                HAVING count(*) > 1
            ) d
            WHERE lower(l.naam) = d.sleutel
              AND l.id <> d.behoud_id
            """
        )
    )

    op.create_index(
        INDEX,
        "leverancier",
        [sa.text("lower(naam)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="leverancier")
