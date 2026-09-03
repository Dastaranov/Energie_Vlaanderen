"""Geef vtest_contract een tijdas, met de publicatiedatum apart.

`vtest_contract` had één rij per `vreg_id` en geen tijdas: alleen
`laatst_gezien_versie`/`laatst_gezien_op`. De contractmetadata — intekenperiode,
start levering, looptijd, doelgroep, prijszekerheid, tariefkaartlink — werd bij
elke import overschreven. Wie in 2028 een contract van september 2026 opzoekt,
kreeg daarmee de *laatste* bekende metadata, niet die van toen. De prijzen
hadden die historiek al wel (`tarief_afname`/`tarief_injectie` dragen
maandelijkse SCD2 sinds januari 2025); de metadata was het gat.

**De tijdas ankert op de scrapedatum**, niet op de publicatiedatum. `geldig_van`
zegt vanaf wanneer deze metadata bij vtest.be écht zo stond. Dat is een
eigenschap van de bron; wanneer wij die gegevens publiceerden is administratie
van deze toepassing en kan er dagen na liggen — versie 20260829T202059Z is op
31 augustus gescrapet en pas op 2 september geïmporteerd. Die twee door elkaar
halen zou de historiek de administratie laten volgen in plaats van de
werkelijkheid.

Daarom staat de publicatiedatum in een **eigen kolom**, `gepubliceerd_op`. Ze
wordt gezet wanneer de versie geactiveerd wordt (`version publish`), niet bij de
import: een versie die wel ingelezen maar nog niet gepubliceerd is, hoort daar
NULL te dragen.

Twee gevolgen die niet los kunnen:

1. **`vreg_id` is niet langer de primaire sleutel.** Er komt een surrogaat `id`
   bij en een unieke sleutel op (`vreg_id`, `geldig_van`) — dezelfde vorm als
   `netbeheerder_tarief` en `tarief_afname`.
2. **De foreign key vanuit `vtest_postcode_prijs.vreg_id` vervalt**, want die
   wees naar een kolom die niet meer uniek is. Er komt een index voor in de
   plaats. Beide tabellen worden in dezelfde transactie uit hetzelfde CSV
   geschreven, dus wezen zijn in de praktijk uitgesloten; het `ON DELETE
   CASCADE` werd bovendien nooit uitgeoefend, omdat een SCD2-tabel niets
   verwijdert. Een `contract_id` die rechtstreeks naar het juiste snapshot
   wijst is de natuurlijke volgende stap, maar valt buiten deze migratie.

De backfill geeft de bestaande rijen de scrapedatum van hun versie
(`vtest_scrape_run`), met `laatst_gezien_op` als terugval. `gepubliceerd_op`
valt terug op `geimporteerd_op` wanneer `geactiveerd_op` leeg is: een versie die
inmiddels vervangen is, heeft haar activatiestempel niet meer staan. Dat is een
benadering en geldt alleen voor rijen van vóór deze migratie.
"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "vtest_postcode_prijs_vreg_id_fkey", "vtest_postcode_prijs", type_="foreignkey"
    )
    op.create_index(
        "ix_vtest_postcode_prijs_vreg_id", "vtest_postcode_prijs", ["vreg_id"]
    )

    op.add_column("vtest_contract", sa.Column("geldig_van", sa.Date(), nullable=True))
    op.add_column("vtest_contract", sa.Column("geldig_tot", sa.Date(), nullable=True))
    op.add_column(
        "vtest_contract",
        sa.Column("gepubliceerd_op", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    # Backfill vóór de NOT NULL: de scrapedatum van de versie waarin het
    # contract het laatst gezien is.
    op.execute(
        """
        UPDATE vtest_contract c
           SET geldig_van = COALESCE(
                   (SELECT MIN(r.scraped_at)::date
                      FROM vtest_scrape_run r
                     WHERE r.version_id = c.laatst_gezien_versie),
                   c.laatst_gezien_op::date
               ),
               gepubliceerd_op = (
                   SELECT COALESCE(v.geactiveerd_op, v.geimporteerd_op)
                     FROM data_version v
                    WHERE v.version_id = c.laatst_gezien_versie
               )
        """
    )
    op.alter_column("vtest_contract", "geldig_van", nullable=False)

    # vreg_id verliest de primaire sleutel; een surrogaat komt ervoor in de
    # plaats, met de tijdas in de unieke sleutel.
    op.drop_constraint("vtest_contract_pkey", "vtest_contract", type_="primary")
    op.add_column(
        "vtest_contract",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=True),
    )
    op.execute("CREATE SEQUENCE vtest_contract_id_seq OWNED BY vtest_contract.id")
    op.execute(
        "ALTER TABLE vtest_contract "
        "ALTER COLUMN id SET DEFAULT nextval('vtest_contract_id_seq')"
    )
    op.execute("UPDATE vtest_contract SET id = nextval('vtest_contract_id_seq')")
    op.alter_column("vtest_contract", "id", nullable=False)
    op.create_primary_key("vtest_contract_pkey", "vtest_contract", ["id"])
    op.create_unique_constraint(
        "uq_vtest_contract_versie", "vtest_contract", ["vreg_id", "geldig_van"]
    )
    op.create_index("ix_vtest_contract_vreg_id", "vtest_contract", ["vreg_id"])


def downgrade() -> None:
    # Alleen het laatste snapshot per contract overleeft: de oude vorm kan er
    # maar één dragen. Oudere snapshots gaan verloren — daarom is dit geen
    # symmetrische terugdraai.
    op.execute(
        """
        DELETE FROM vtest_contract c
         WHERE EXISTS (
             SELECT 1 FROM vtest_contract n
              WHERE n.vreg_id = c.vreg_id AND n.geldig_van > c.geldig_van
         )
        """
    )
    op.drop_index("ix_vtest_contract_vreg_id", table_name="vtest_contract")
    op.drop_constraint("uq_vtest_contract_versie", "vtest_contract", type_="unique")
    op.drop_constraint("vtest_contract_pkey", "vtest_contract", type_="primary")
    op.drop_column("vtest_contract", "id")
    op.execute("DROP SEQUENCE IF EXISTS vtest_contract_id_seq")
    op.create_primary_key("vtest_contract_pkey", "vtest_contract", ["vreg_id"])
    op.drop_column("vtest_contract", "gepubliceerd_op")
    op.drop_column("vtest_contract", "geldig_tot")
    op.drop_column("vtest_contract", "geldig_van")
    op.drop_index("ix_vtest_postcode_prijs_vreg_id", table_name="vtest_postcode_prijs")
    op.create_foreign_key(
        "vtest_postcode_prijs_vreg_id_fkey", "vtest_postcode_prijs",
        "vtest_contract", ["vreg_id"], ["vreg_id"], ondelete="CASCADE",
    )
