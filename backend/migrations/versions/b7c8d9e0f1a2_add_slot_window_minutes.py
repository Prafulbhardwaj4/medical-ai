"""add window_minutes to doctor_slots (per-patient time-splitting)"""
from alembic import op
import sqlalchemy as sa

revision = 'b7c8d9e0f1a2'
down_revision = 'a1e2f3g4h5i6'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c['name'] for c in insp.get_columns('doctor_slots')]
    if 'window_minutes' not in cols:
        op.add_column('doctor_slots', sa.Column('window_minutes', sa.Integer(), nullable=False, server_default='60'))


def downgrade():
    op.drop_column('doctor_slots', 'window_minutes')