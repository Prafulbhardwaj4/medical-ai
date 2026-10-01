"""C5: record how each pharmacy payment was collected (cash/card/upi)"""
from alembic import op
import sqlalchemy as sa

revision = 'd3e5f7a9b1c2'
down_revision = 'c2d4e6f8a0b1'
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    cols = {c['name'] for c in insp.get_columns('medicine_orders')}
    if 'payment_method' not in cols:
        op.add_column('medicine_orders', sa.Column('payment_method', sa.String(), nullable=True))


def downgrade():
    op.drop_column('medicine_orders', 'payment_method')