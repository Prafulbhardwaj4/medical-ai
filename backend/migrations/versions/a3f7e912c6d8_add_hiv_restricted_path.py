"""add HIV-authorization flag, HIV test flag, and counselling tracking"""
from alembic import op
import sqlalchemy as sa

revision = '8c5de10471cc'
down_revision = 'z8d9e0f1a2b3'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    doctor_cols = {c['name'] for c in insp.get_columns('doctors')}
    if 'is_hiv_authorized' not in doctor_cols:
        op.add_column('doctors', sa.Column('is_hiv_authorized', sa.Boolean(), nullable=False, server_default='false'))

    item_cols = {c['name'] for c in insp.get_columns('test_catalog_items')}
    if 'is_hiv_test' not in item_cols:
        op.add_column('test_catalog_items', sa.Column('is_hiv_test', sa.Boolean(), nullable=False, server_default='false'))

    order_cols = {c['name'] for c in insp.get_columns('test_orders')}
    if 'hiv_counselling_completed' not in order_cols:
        op.add_column('test_orders', sa.Column('hiv_counselling_completed', sa.Boolean(), nullable=False, server_default='false'))


def downgrade():
    op.drop_column('test_orders', 'hiv_counselling_completed')
    op.drop_column('test_catalog_items', 'is_hiv_test')
    op.drop_column('doctors', 'is_hiv_authorized')