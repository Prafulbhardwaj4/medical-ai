"""add critical_low/critical_high to test catalog items and parameters"""
from alembic import op
import sqlalchemy as sa

revision = 'e9f0a1b2c3d4'
down_revision = 'd8e9f0a1b2c3'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    item_cols = {c['name'] for c in insp.get_columns('test_catalog_items')}
    if 'critical_low' not in item_cols:
        op.add_column('test_catalog_items', sa.Column('critical_low', sa.Float(), nullable=True))
    if 'critical_high' not in item_cols:
        op.add_column('test_catalog_items', sa.Column('critical_high', sa.Float(), nullable=True))

    if 'test_catalog_parameters' not in insp.get_table_names():
        op.create_table(
            'test_catalog_parameters',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('test_catalog_item_id', sa.Integer(), sa.ForeignKey('test_catalog_items.id'), nullable=False),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('unit', sa.String(), nullable=True),
            sa.Column('reference_range_male', sa.String(), nullable=True),
            sa.Column('reference_range_female', sa.String(), nullable=True),
            sa.Column('purpose', sa.Text(), nullable=True),
            sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        insp = sa.inspect(bind)
    param_cols = {c['name'] for c in insp.get_columns('test_catalog_parameters')}
    if 'critical_low' not in param_cols:
        op.add_column('test_catalog_parameters', sa.Column('critical_low', sa.Float(), nullable=True))
    if 'critical_high' not in param_cols:
        op.add_column('test_catalog_parameters', sa.Column('critical_high', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('test_catalog_parameters', 'critical_high')
    op.drop_column('test_catalog_parameters', 'critical_low')
    op.drop_column('test_catalog_items', 'critical_high')
    op.drop_column('test_catalog_items', 'critical_low')