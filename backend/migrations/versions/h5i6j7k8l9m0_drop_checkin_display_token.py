"""drop checkins.display_token — short-serial-number experiment reverted, back to showing the actual token_number everywhere"""
from alembic import op
import sqlalchemy as sa

revision = 'h5i6j7k8l9m0'
down_revision = 'g4h5i6j7k8l9'  # current head per your alembic_version — verify with `alembic heads` before running, same as always
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    checkin_cols = {c['name'] for c in insp.get_columns('checkins')}
    if 'display_token' in checkin_cols:
        op.drop_column('checkins', 'display_token')


def downgrade():
    op.add_column('checkins', sa.Column('display_token', sa.Integer(), nullable=True))