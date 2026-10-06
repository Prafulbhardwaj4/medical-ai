"""stock moves at Mark Sent (store batch allocations) + appointment cancelled_by"""
from alembic import op
import sqlalchemy as sa

revision = 'k4d5e6f7a8b9'
down_revision = 'j3c4d5e6f7a8'  # your latest migration. If `alembic heads` shows another, use that one.


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('admission_medication_orders')}
    if 'stock_allocations' not in cols:
        op.add_column('admission_medication_orders', sa.Column('stock_allocations', sa.Text(), nullable=True))
    cols = {c['name'] for c in insp.get_columns('portal_appointments')}
    if 'cancelled_by' not in cols:
        op.add_column('portal_appointments', sa.Column('cancelled_by', sa.String(), nullable=True))


def downgrade():
    op.drop_column('portal_appointments', 'cancelled_by')
    op.drop_column('admission_medication_orders', 'stock_allocations')