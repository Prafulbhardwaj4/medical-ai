"""add fasting_required to test_catalog_items"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'test_catalog_items' not in insp.get_table_names():
        op.create_table(
            'test_catalog_items',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('fee', sa.Float(), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        insp = sa.inspect(bind)
    existing_cols = {c['name'] for c in insp.get_columns('test_catalog_items')}
    if 'fasting_required' not in existing_cols:
        op.add_column('test_catalog_items', sa.Column('fasting_required', sa.Boolean(), nullable=False, server_default='false'))


def downgrade():
    op.drop_column('test_catalog_items', 'fasting_required')