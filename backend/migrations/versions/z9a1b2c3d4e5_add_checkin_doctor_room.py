"""add checkins.doctor_room — room stored at token-issue time so slips don't change later"""
from alembic import op
import sqlalchemy as sa

revision = 'z9a1b2c3d4e5'
down_revision = 'h5i6j7k8l9m0'  # <-- set to your real current head (`alembic heads`) before running
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    checkin_cols = {c['name'] for c in insp.get_columns('checkins')}
    if 'doctor_room' not in checkin_cols:
        op.add_column('checkins', sa.Column('doctor_room', sa.String(), nullable=True))


def downgrade():
    op.drop_column('checkins', 'doctor_room')