"""add checkins.display_token — short human-callable per-day token number"""
from alembic import op
import sqlalchemy as sa

revision = 'b3c4d5e6f7a9'
down_revision = 'c9d8e7f6a5b4'  # PLACEHOLDER — verify against `alembic heads` and fix before running
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    checkin_cols = {c['name'] for c in insp.get_columns('checkins')}
    if 'display_token' not in checkin_cols:
        op.add_column('checkins', sa.Column('display_token', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('checkins', 'display_token')