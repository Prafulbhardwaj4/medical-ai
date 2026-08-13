"""add up_next_skip flag to checkins"""
from alembic import op
import sqlalchemy as sa

revision = '6d184c9b1415'
down_revision = 'b8f4a1e6d3c9'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('checkins')}
    if 'up_next_skip' not in cols:
        op.add_column('checkins', sa.Column('up_next_skip', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('checkins', 'up_next_skip')