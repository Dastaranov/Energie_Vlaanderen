"""Verbreed netbeheerder_tarief.prijs van zes naar zeven decimalen.

VREG publiceert de distributienettarieven met **zeven** decimalen. De kolom
stond op `Numeric(14, 6)`, dus elk tarief met een zevende decimaal werd bij het
invoegen stil afgerond: 0,0230382 werd 0,023038 en 0,0000145 werd 0,000015.

Het raakt geen randgeval maar de meerderheid: 186 van de 272 gasrijen en 513
van de 776 elektriciteitsrijen in het werkboek van 2026 dragen zeven decimalen.

Precies dezelfde fout als `vaste_vergoeding_jaar` in migratie 0022, en om
dezelfde reden de moeite: het bedrag is verwaarloosbaar — het grootste verlies
is 5e-7 EUR/kWh, op een jaarverbruik van 12.181 kWh een halve eurocent per
component — maar het is afronding van *brondata*. En het maakt een exacte
audit op deze kolom onmogelijk: `audit golden` meldt 186 verschillen die geen
van alle een echte afwijking zijn. Daar een tolerantie voor inbouwen zou de
kolom juist onbewaakt laten, wat dan weer een échte afwijking zou verbergen.

De integerruimte blijft gelijk: 14-6 en 15-7 laten allebei acht cijfers vóór de
komma, ruim voor het hoogste tarief in de tabel (een vaste term van enkele
duizenden euro bij GAS_T4).

De decimalen komen terug bij de eerstvolgende import; het werkboek is de bron
en blijft bewaard. Deze migratie verbreedt alleen de kolom.
"""
from alembic import op
import sqlalchemy as sa

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "netbeheerder_tarief",
        "prijs",
        existing_type=sa.Numeric(14, 6),
        type_=sa.Numeric(15, 7),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Terugdraaien rondt af en verliest de zevende decimaal opnieuw. Dat is
    # onvermijdelijk bij een versmalling; de bron blijft het werkboek.
    op.alter_column(
        "netbeheerder_tarief",
        "prijs",
        existing_type=sa.Numeric(15, 7),
        type_=sa.Numeric(14, 6),
        existing_nullable=True,
    )
