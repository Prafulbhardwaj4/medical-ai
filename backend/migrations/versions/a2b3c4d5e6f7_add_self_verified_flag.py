"""add self_verified_sole_staff flag to test_orders"""
from alembic import op
import sqlalchemy as sa

revision = 'a2b3c4d5e6f7'
down_revision = 'c3d4e5f6a7b8'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('test_orders')}
    if 'self_verified_sole_staff' not in cols:
        op.add_column('test_orders', sa.Column('self_verified_sole_staff', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('test_orders', 'self_verified_sole_staff')