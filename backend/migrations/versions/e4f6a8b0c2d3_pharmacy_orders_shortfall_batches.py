"""C8 shortfall column on medicine_orders + C12 medicine_order_batches (batch used per dispense)"""
from alembic import op
import sqlalchemy as sa

revision = 'e4f6a8b0c2d3'
down_revision = 'd3e5f7a9b1c2'
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    cols = {c['name'] for c in insp.get_columns('medicine_orders')}
    if 'shortfall_quantity' not in cols:
        op.add_column('medicine_orders', sa.Column('shortfall_quantity', sa.Integer(), nullable=True))
    if 'medicine_order_batches' not in insp.get_table_names():
        op.create_table(
            'medicine_order_batches',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('order_id', sa.Integer(), sa.ForeignKey('medicine_orders.id'), nullable=False),
            sa.Column('batch_id', sa.Integer(), sa.ForeignKey('medicine_batches.id'), nullable=True),
            sa.Column('batch_number', sa.String(), nullable=True),
            sa.Column('quantity', sa.Integer(), nullable=False),
        )
        op.create_index('ix_medicine_order_batches_order_id', 'medicine_order_batches', ['order_id'])


def downgrade():
    op.drop_index('ix_medicine_order_batches_order_id', table_name='medicine_order_batches')
    op.drop_table('medicine_order_batches')
    op.drop_column('medicine_orders', 'shortfall_quantity')