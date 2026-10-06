"""test_orders.result_snapshot: frozen units/ranges/parameter names at result entry"""
from alembic import op
import sqlalchemy as sa

revision = 'c5a1f0b7d2e9'
down_revision = 'e4f6a8b0c2d3'
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    cols = {c['name'] for c in insp.get_columns('test_orders')}
    if 'result_snapshot' not in cols:
        op.add_column('test_orders', sa.Column('result_snapshot', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('test_orders', 'result_snapshot')