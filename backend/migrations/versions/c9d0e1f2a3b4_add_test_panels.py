"""add is_panel/purpose to test_catalog_items, add test_catalog_parameters table"""
from alembic import op
import sqlalchemy as sa

revision = 'c9d0e1f2a3b4'
down_revision = 'b8c9d0e1f2a3'

def upgrade():
    op.add_column('test_catalog_items', sa.Column('is_panel', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('test_catalog_items', sa.Column('purpose', sa.Text(), nullable=True))

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

def downgrade():
    op.drop_table('test_catalog_parameters')
    op.drop_column('test_catalog_items', 'purpose')
    op.drop_column('test_catalog_items', 'is_panel')