"""add emergency reason and destination fields"""
from alembic import op
import sqlalchemy as sa

revision = 'z9e0f1a2b3c4'
down_revision = 'z2b3c4d5e6f7'  # <-- adjust to your real current head before running


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    checkin_cols = {c['name'] for c in insp.get_columns('checkins')}
    if 'emergency_reason' not in checkin_cols:
        op.add_column('checkins', sa.Column('emergency_reason', sa.Text(), nullable=True))
    if 'emergency_destination' not in checkin_cols:
        op.add_column('checkins', sa.Column('emergency_destination', sa.String(), nullable=True))


def downgrade():
    op.drop_column('checkins', 'emergency_destination')
    op.drop_column('checkins', 'emergency_reason')