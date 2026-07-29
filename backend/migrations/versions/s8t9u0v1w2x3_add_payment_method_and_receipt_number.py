"""add payment_method to checkins/test_orders and receipt_number to invoices"""
from alembic import op
import sqlalchemy as sa

revision = 's8t9u0v1w2x3'
down_revision = 'r8t9u0v1w2x3'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    checkin_cols = {c['name'] for c in insp.get_columns('checkins')}
    if 'payment_method' not in checkin_cols:
        op.add_column('checkins', sa.Column('payment_method', sa.String(), nullable=True))

    test_order_cols = {c['name'] for c in insp.get_columns('test_orders')}
    if 'payment_method' not in test_order_cols:
        op.add_column('test_orders', sa.Column('payment_method', sa.String(), nullable=True))

    invoice_cols = {c['name'] for c in insp.get_columns('invoices')}
    if 'receipt_number' not in invoice_cols:
        op.add_column('invoices', sa.Column('receipt_number', sa.String(), nullable=True))
        op.create_index('ix_invoices_receipt_number', 'invoices', ['receipt_number'], unique=True)


def downgrade():
    op.drop_index('ix_invoices_receipt_number', table_name='invoices')
    op.drop_column('invoices', 'receipt_number')
    op.drop_column('test_orders', 'payment_method')
    op.drop_column('checkins', 'payment_method')