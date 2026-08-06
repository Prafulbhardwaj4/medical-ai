"""add emergency_status to checkins (Emergency Ward holding state)"""
from alembic import op
import sqlalchemy as sa

revision = 'a1e2f3g4h5i6'
down_revision = 'd7e6f5a4b3c2'  # confirmed via `alembic heads` against your actual DB — this is your real current head


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c['name'] for c in insp.get_columns('checkins')]
    if 'emergency_status' not in cols:
        op.add_column('checkins', sa.Column('emergency_status', sa.String(), nullable=True))


def downgrade():
    op.drop_column('checkins', 'emergency_status')