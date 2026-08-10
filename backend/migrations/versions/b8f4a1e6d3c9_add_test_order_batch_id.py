"""add order_batch_id to test_orders for report grouping"""
from alembic import op
import sqlalchemy as sa

revision = 'b8f4a1e6d3c9'
down_revision = 'a4d7e2c9f6b1'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('test_orders')}
    if 'order_batch_id' not in cols:
        op.add_column('test_orders', sa.Column('order_batch_id', sa.String(), nullable=True))
        op.create_index('ix_test_orders_order_batch_id', 'test_orders', ['order_batch_id'])


def downgrade():
    op.drop_index('ix_test_orders_order_batch_id', table_name='test_orders')
    op.drop_column('test_orders', 'order_batch_id')