"""add appointment arrived_at and checkin queue_priority_time"""
from alembic import op
import sqlalchemy as sa

revision = 'e3f4a5b6c7d8'
down_revision = 'd2e3f4a5b6c7'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    appt_cols = {c['name'] for c in insp.get_columns('portal_appointments')}
    if 'arrived_at' not in appt_cols:
        op.add_column('portal_appointments', sa.Column('arrived_at', sa.DateTime(), nullable=True))

    checkin_cols = {c['name'] for c in insp.get_columns('checkins')}
    if 'queue_priority_time' not in checkin_cols:
        op.add_column('checkins', sa.Column('queue_priority_time', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('checkins', 'queue_priority_time')
    op.drop_column('portal_appointments', 'arrived_at')