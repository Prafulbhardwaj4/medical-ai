"""add is_out_of_stock and substitute_for_id to admission_medication_orders

Pharmacy currently has no way to flag an admitted-patient medicine order as
unfulfillable at the counter. These columns support: (1) flagging an order
out of stock without touching its billing/stock deduction (those already
happened upfront at order time), and (2) linking a replacement order back
to the original it substitutes.

Revision ID: e1f2a3b4c5d6
Revises: b3f4a5c6d7e8
Create Date: 2026-08-22 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = 'e1f2a3b4c5d6'
down_revision = 'b3f4a5c6d7e8'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('admission_medication_orders')}
    if 'is_out_of_stock' not in cols:
        op.add_column('admission_medication_orders', sa.Column('is_out_of_stock', sa.Boolean(), nullable=False, server_default='0'))
    if 'substitute_for_id' not in cols:
        if bind.dialect.name == 'sqlite':
            # SQLite supports ADD COLUMN with an inline FK reference directly via
            # raw SQL — it's only Alembic's batch-mode table-recreate that trips
            # on unnamed pre-existing constraints on this table, not SQLite itself.
            op.execute('ALTER TABLE admission_medication_orders ADD COLUMN substitute_for_id INTEGER REFERENCES admission_medication_orders(id)')
        else:
            op.add_column('admission_medication_orders', sa.Column('substitute_for_id', sa.Integer(), sa.ForeignKey('admission_medication_orders.id'), nullable=True))


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        op.execute('ALTER TABLE admission_medication_orders DROP COLUMN substitute_for_id')
        op.execute('ALTER TABLE admission_medication_orders DROP COLUMN is_out_of_stock')
    else:
        op.drop_column('admission_medication_orders', 'substitute_for_id')
        op.drop_column('admission_medication_orders', 'is_out_of_stock')