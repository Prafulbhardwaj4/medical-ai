"""add same-day return queue fields to checkins"""
from alembic import op
import sqlalchemy as sa

revision = 'z3c4d5e6f7g8'
down_revision = 'z2b3c4d5e6f7'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    checkin_cols = {c['name'] for c in insp.get_columns('checkins')}
    if 'is_returned' not in checkin_cols:
        op.add_column('checkins', sa.Column('is_returned', sa.Boolean(), nullable=False, server_default='false'))
    if 'returned_at' not in checkin_cols:
        op.add_column('checkins', sa.Column('returned_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('checkins', 'returned_at')
    op.drop_column('checkins', 'is_returned')