"""Leg vast uit welke bronversie een nettarief komt.

`netbeheerder_tarief` droeg `source_sheet` en `source_row` — waar in het
werkboek een rij vandaan kwam — maar niet uit wélk werkboek. Zolang er één
tariefjaar in de databank stond viel dat niet op. Zodra er meerdere jaargangen
naast elkaar staan, en zeker zodra een jaargang buiten de gewone
publicatieketen bijgeladen wordt, is dat een gat: de data klopt, maar niets zegt
waar ze vandaan komt en een herbouw vanuit de bronnen reproduceert ze niet.

Manifest §"Key design rules": herkomst is verplicht op elke afgeleide waarde.
Een tariefrij is een afgeleide waarde.

Bestaande rijen blijven NULL. Ze raden zou een herkomst verzinnen die niet
vastgesteld is; ze vullen zich vanzelf bij de eerstvolgende import van hun
jaargang.
"""
from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "netbeheerder_tarief",
        sa.Column("bron_versie", sa.String(26), nullable=True),
    )
    op.create_index(
        "ix_netbeheerder_tarief_bron_versie", "netbeheerder_tarief", ["bron_versie"]
    )


def downgrade() -> None:
    op.drop_index("ix_netbeheerder_tarief_bron_versie", table_name="netbeheerder_tarief")
    op.drop_column("netbeheerder_tarief", "bron_versie")
