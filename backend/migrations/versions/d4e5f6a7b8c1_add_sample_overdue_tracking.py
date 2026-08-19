"""add sample_overdue_notified_at to test_orders"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c1'
down_revision = 'f9b2d6e4c8a1'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('test_orders')}
    if 'sample_overdue_notified_at' not in cols:
        op.add_column('test_orders', sa.Column('sample_overdue_notified_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('test_orders', 'sample_overdue_notified_at')