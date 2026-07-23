"""add payment_method to invoices"""
from alembic import op
import sqlalchemy as sa

revision = 'l1m2n3o4p5q6'
down_revision = 'k0l1m2n3o4p5'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('invoices')}
    if 'payment_method' not in cols:
        op.add_column('invoices', sa.Column('payment_method', sa.String(), nullable=True))


def downgrade():
    op.drop_column('invoices', 'payment_method')