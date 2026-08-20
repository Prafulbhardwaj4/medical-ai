"""add quantity (strips/units dispensed) to admission_medication_orders

Medicine billing on admissions is moving from per-dose-administered to
per-order — the full quantity is deducted from stock and billed once,
upfront, when the order is placed (matches how a real strip/bottle is
physically handed over). This column records how many units/strips were
ordered so the amount can be recomputed/audited later.
"""
from alembic import op
import sqlalchemy as sa

revision = 'b3f4a5c6d7e8'
down_revision = 'd4e5f6a7b8c1'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('admission_medication_orders')}
    if 'quantity' not in cols:
        op.add_column('admission_medication_orders', sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'))


def downgrade():
    op.drop_column('admission_medication_orders', 'quantity')