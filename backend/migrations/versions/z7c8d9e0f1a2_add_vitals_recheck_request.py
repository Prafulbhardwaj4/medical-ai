"""add vitals recheck request field for send-back-for-more-vitals loop"""
from alembic import op
import sqlalchemy as sa

revision = 'z7c8d9e0f1a2'
down_revision = 'z5b6c7d8e9f0'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    checkin_cols = {c['name'] for c in insp.get_columns('checkins')}
    if 'vitals_recheck_request' not in checkin_cols:
        op.add_column('checkins', sa.Column('vitals_recheck_request', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('checkins', 'vitals_recheck_request')