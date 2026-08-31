"""Rebuild product schema: from EAV to fixed columns, add scrape tables, add heffingen.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-31 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old tables in FK-safe order
    op.drop_table('vtest_product_match')
    op.drop_table('product_component')
    op.drop_table('vtest_product')
    op.drop_table('leverancier_product')
    op.drop_table('netwerk_tarief')

    # Create new leverancier table
    op.create_table(
        'leverancier',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('naam', sa.Text(), nullable=False),
        sa.Column('website_url', sa.Text(), nullable=True),
        sa.Column('klantendienst_telefoon', sa.Text(), nullable=True),
        sa.Column('klantendienst_email', sa.Text(), nullable=True),
        sa.Column('vreg_service_score', sa.Numeric(precision=3, scale=1), nullable=True),
        sa.Column('bijgewerkt_op', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('naam', name='leverancier_naam_key')
    )

    # Create new energie_product table
    op.create_table(
        'energie_product',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('leverancier_id', sa.Integer(), nullable=False),
        sa.Column('vreg_id', sa.Text(), nullable=True),
        sa.Column('product_naam', sa.Text(), nullable=False),
        sa.Column('energie_type', sa.Text(), nullable=False),
        sa.Column('segment', sa.Text(), nullable=False),
        sa.Column('tariefkaart_url', sa.Text(), nullable=True),
        sa.Column('bijzondere_voorwaarden_url', sa.Text(), nullable=True),
        sa.Column('groene_stroom', sa.Boolean(), nullable=True),
        sa.Column('aangemaakt_op', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['leverancier_id'], ['leverancier.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('leverancier_id', 'product_naam', 'energie_type', 'segment', name='uq_energie_product_identiteit'),
        sa.UniqueConstraint('vreg_id', name='energie_product_vreg_id_key')
    )

    # Create tarief_afname table
    op.create_table(
        'tarief_afname',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('product_id', sa.BigInteger(), nullable=False),
        sa.Column('meter_type', sa.Text(), nullable=False),
        sa.Column('prijs_type', sa.Text(), nullable=False),
        sa.Column('energieprijs_kwh', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('vaste_vergoeding_jaar', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('groene_stroom_kwh', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('wkk_kwh', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('energiebijdrage_kwh', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('param_a', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('param_b', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('param_c', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('param_d', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('param_z', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('index_naam_a', sa.Text(), nullable=True),
        sa.Column('index_naam_b', sa.Text(), nullable=True),
        sa.Column('index_naam_c', sa.Text(), nullable=True),
        sa.Column('index_naam_d', sa.Text(), nullable=True),
        sa.Column('index_waarde_a', sa.Numeric(precision=14, scale=6), nullable=True),
        sa.Column('index_waarde_b', sa.Numeric(precision=14, scale=6), nullable=True),
        sa.Column('index_waarde_c', sa.Numeric(precision=14, scale=6), nullable=True),
        sa.Column('index_waarde_d', sa.Numeric(precision=14, scale=6), nullable=True),
        sa.Column('geldig_van', sa.Date(), nullable=False),
        sa.Column('geldig_tot', sa.Date(), nullable=True),
        sa.Column('bron_bestand', sa.Text(), nullable=True),
        sa.Column('source_row', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['product_id'], ['energie_product.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_tarief_afname_lookup', 'tarief_afname', ['product_id', 'geldig_van', 'geldig_tot'], unique=False)
    op.create_index('ix_tarief_afname_open', 'tarief_afname', ['product_id', 'meter_type'], unique=True,
                    postgresql_where=sa.text('geldig_tot IS NULL'))

    # Create tarief_injectie table
    op.create_table(
        'tarief_injectie',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('product_id', sa.BigInteger(), nullable=False),
        sa.Column('meter_type', sa.Text(), nullable=False),
        sa.Column('prijs_type', sa.Text(), nullable=False),
        sa.Column('energieprijs_kwh', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('vaste_vergoeding_jaar', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('groene_stroom_kwh', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('wkk_kwh', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('energiebijdrage_kwh', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('param_a', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('param_b', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('param_c', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('param_d', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('param_z', sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column('index_naam_a', sa.Text(), nullable=True),
        sa.Column('index_naam_b', sa.Text(), nullable=True),
        sa.Column('index_naam_c', sa.Text(), nullable=True),
        sa.Column('index_naam_d', sa.Text(), nullable=True),
        sa.Column('index_waarde_a', sa.Numeric(precision=14, scale=6), nullable=True),
        sa.Column('index_waarde_b', sa.Numeric(precision=14, scale=6), nullable=True),
        sa.Column('index_waarde_c', sa.Numeric(precision=14, scale=6), nullable=True),
        sa.Column('index_waarde_d', sa.Numeric(precision=14, scale=6), nullable=True),
        sa.Column('geldig_van', sa.Date(), nullable=False),
        sa.Column('geldig_tot', sa.Date(), nullable=True),
        sa.Column('bron_bestand', sa.Text(), nullable=True),
        sa.Column('source_row', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['product_id'], ['energie_product.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_tarief_injectie_open', 'tarief_injectie', ['product_id', 'meter_type'], unique=True,
                    postgresql_where=sa.text('geldig_tot IS NULL'))

    # Create vtest_contract table
    op.create_table(
        'vtest_contract',
        sa.Column('vreg_id', sa.Text(), nullable=False),
        sa.Column('leverancier_raw', sa.Text(), nullable=False),
        sa.Column('product_raw', sa.Text(), nullable=False),
        sa.Column('energie_type', sa.Text(), nullable=True),
        sa.Column('tarief_type', sa.Text(), nullable=True),
        sa.Column('looptijd_tekst', sa.Text(), nullable=True),
        sa.Column('looptijd_maanden', sa.SmallInteger(), nullable=True),
        sa.Column('datum_intekenen_van', sa.Date(), nullable=True),
        sa.Column('datum_intekenen_tot', sa.Date(), nullable=True),
        sa.Column('datum_start_levering_van', sa.Date(), nullable=True),
        sa.Column('datum_start_levering_tot', sa.Date(), nullable=True),
        sa.Column('doelgroep_zonnepanelen', sa.Text(), nullable=True),
        sa.Column('doelgroep_ev', sa.Text(), nullable=True),
        sa.Column('doelgroep_energiedelen', sa.Text(), nullable=True),
        sa.Column('doelgroep_leegstand', sa.Text(), nullable=True),
        sa.Column('doelgroep_groepsaankoop', sa.Text(), nullable=True),
        sa.Column('prijszekerheid_termijn', sa.Text(), nullable=True),
        sa.Column('link_tariefkaart', sa.Text(), nullable=True),
        sa.Column('link_voorwaarden', sa.Text(), nullable=True),
        sa.Column('link_supplier', sa.Text(), nullable=True),
        sa.Column('contracttype', sa.Text(), nullable=True),
        sa.Column('supplier_id', sa.Text(), nullable=True),
        sa.Column('product_id', sa.Text(), nullable=True),
        sa.Column('green_type', sa.Text(), nullable=True),
        sa.Column('stars', sa.Text(), nullable=True),
        sa.Column('complex_product', sa.Boolean(), nullable=True),
        sa.Column('grayedout', sa.Boolean(), nullable=True),
        sa.Column('laatst_gezien_versie', sa.String(length=26), nullable=False),
        sa.Column('laatst_gezien_op', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['laatst_gezien_versie'], ['data_version.version_id'], ),
        sa.PrimaryKeyConstraint('vreg_id')
    )

    # Create vtest_postcode_prijs table
    op.create_table(
        'vtest_postcode_prijs',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('vreg_id', sa.Text(), nullable=False),
        sa.Column('postcode', sa.String(length=10), nullable=False),
        sa.Column('segment', sa.Text(), nullable=False),
        sa.Column('version_id', sa.String(length=26), nullable=False),
        sa.Column('discount_eur', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('total_excl_btw', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('total_incl_btw', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('btw_bedrag', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('totaal_verbruik_kwh', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('prijs_indicatie_eur', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('scraped_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['version_id'], ['data_version.version_id'], ),
        sa.ForeignKeyConstraint(['vreg_id'], ['vtest_contract.vreg_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('vreg_id', 'postcode', 'version_id', name='uq_vtest_postcode_prijs')
    )

    # Create netbeheerder_tarief table (replacing netwerk_tarief)
    op.create_table(
        'netbeheerder_tarief',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('netbeheerder_code', sa.String(length=40), nullable=False),
        sa.Column('energie_type', sa.Text(), nullable=False),
        sa.Column('contract_richting', sa.Text(), nullable=False),
        sa.Column('klanttype', sa.Text(), nullable=False),
        sa.Column('tarieftype', sa.Text(), nullable=True),
        sa.Column('tariefdetail', sa.Text(), nullable=True),
        sa.Column('tariefnotering', sa.Text(), nullable=True),
        sa.Column('prijs', sa.Numeric(precision=14, scale=6), nullable=True),
        sa.Column('geldig_van', sa.Date(), nullable=False),
        sa.Column('geldig_tot', sa.Date(), nullable=True),
        sa.Column('source_sheet', sa.Text(), nullable=True),
        sa.Column('source_row', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['netbeheerder_code'], ['netbeheerder.code'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('netbeheerder_code', 'energie_type', 'contract_richting', 'klanttype', 'tarieftype', 'tariefdetail', 'geldig_van', name='uq_netbeheerder_tarief')
    )
    op.create_index('ix_netbeheerder_tarief_open', 'netbeheerder_tarief',
                    ['netbeheerder_code', 'energie_type', 'klanttype', 'tarieftype', 'tariefdetail'],
                    unique=True, postgresql_where=sa.text('geldig_tot IS NULL'))

    # Create heffingen tables
    op.create_table(
        'overheidsheffing_accijns_schijf',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('energievorm', sa.Text(), nullable=False),
        sa.Column('klantcategorie', sa.Text(), nullable=False),
        sa.Column('van_mwh', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('tot_mwh', sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column('accijns_eur_mwh', sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column('bijzondere_accijns_eur_mwh', sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column('energiebijdrage_eur_mwh', sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column('bron', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'overheidsheffing_energiefonds',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('jaar', sa.SmallInteger(), nullable=False),
        sa.Column('spanningsniveau', sa.Text(), nullable=False),
        sa.Column('klantcategorie', sa.Text(), nullable=False, server_default=''),
        sa.Column('eur_per_maand', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('bron', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('jaar', 'spanningsniveau', 'klantcategorie', name='uq_overheidsheffing_energiefonds')
    )

    op.create_table(
        'overheidsheffing_btw',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('component', sa.Text(), nullable=False),
        sa.Column('percentage', sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column('vrijgesteld', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('geldig_vanaf', sa.Date(), nullable=False),
        sa.Column('bron', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('component', 'geldig_vanaf', name='uq_overheidsheffing_btw')
    )


def downgrade() -> None:
    # Drop new tables in reverse order
    op.drop_table('overheidsheffing_btw')
    op.drop_table('overheidsheffing_energiefonds')
    op.drop_table('overheidsheffing_accijns_schijf')
    op.drop_index('ix_netbeheerder_tarief_open', table_name='netbeheerder_tarief')
    op.drop_table('netbeheerder_tarief')
    op.drop_table('vtest_postcode_prijs')
    op.drop_table('vtest_contract')
    op.drop_index('ix_tarief_injectie_open', table_name='tarief_injectie')
    op.drop_table('tarief_injectie')
    op.drop_index('ix_tarief_afname_open', table_name='tarief_afname')
    op.drop_index('ix_tarief_afname_lookup', table_name='tarief_afname')
    op.drop_table('tarief_afname')
    op.drop_table('energie_product')
    op.drop_table('leverancier')

    # Recreate old tables (downgrade path is incomplete on purpose - this is a destructive change)
    raise NotImplementedError("Downgrade not supported for this schema rebuild migration")
