"""test_orders.amended_at / amended_by / amendment_reason"""
from alembic import op
import sqlalchemy as sa

revision = 'b7c6d5e4f3a2'
down_revision = 'a9b8c7d6e5f4'
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    cols = {c['name'] for c in insp.get_columns('test_orders')}
    if 'amended_at' not in cols:
        op.add_column('test_orders', sa.Column('amended_at', sa.DateTime(), nullable=True))
    if 'amended_by' not in cols:
        op.add_column('test_orders', sa.Column('amended_by', sa.Integer(), nullable=True))
    if 'amendment_reason' not in cols:
        op.add_column('test_orders', sa.Column('amendment_reason', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('test_orders', 'amendment_reason')
    op.drop_column('test_orders', 'amended_by')
    op.drop_column('test_orders', 'amended_at')