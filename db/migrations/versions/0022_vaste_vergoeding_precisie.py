"""Bewaar de vaste vergoeding zonder stille afronding.

`vaste_vergoeding_jaar` stond op `Numeric(10, 2)` terwijl elke andere
prijskolom in dezelfde tabel `Numeric(12, 6)` is. De V-test-export geeft
61,321 EUR/jaar; de databank maakte er 61,32 van, en 11,2075 werd 11,21. Bij
4.631 van de tariefrijen wijkt de opgeslagen waarde daardoor af van de bron.

Het bedrag is klein — een duizendste euro per jaar — maar dat is niet het punt.
Het is een stille afronding van brondata, en dit project rondt brondata niet af
"omdat het toch weinig scheelt": dezelfde redenering hield elders een verkeerd
getal maandenlang in stand. Bovendien maakt ze een cel-voor-cel-audit tegen het
werkboek onmogelijk: je zou een tolerantie moeten inbouwen, en een audit met
tolerantie op een kolom die exact hoort te zijn, bewaakt die kolom niet meer.

Deze migratie verbreedt de kolom. De reeds afgeronde waarden komen er niet mee
terug — daarvoor is een herimport nodig, want de weggelaten decimalen staan
alleen nog in het werkboek.
"""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for tabel in ("tarief_afname", "tarief_injectie"):
        op.alter_column(
            tabel, "vaste_vergoeding_jaar",
            type_=sa.Numeric(12, 6), existing_type=sa.Numeric(10, 2),
            existing_nullable=True,
        )


def downgrade() -> None:
    # Terug naar twee decimalen rondt opnieuw af; de precisie is dan weg.
    for tabel in ("tarief_afname", "tarief_injectie"):
        op.alter_column(
            tabel, "vaste_vergoeding_jaar",
            type_=sa.Numeric(10, 2), existing_type=sa.Numeric(12, 6),
            existing_nullable=True,
        )
