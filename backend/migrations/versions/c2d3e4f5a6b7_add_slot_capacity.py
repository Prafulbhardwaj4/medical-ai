"""replace doctor_slots.is_booked with capacity/booked_count for crowd-level tracking"""
from alembic import op
import sqlalchemy as sa

revision = 'c2d3e4f5a6b7'
down_revision = 'b1c2d3e4f5a6'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = {c['name'] for c in insp.get_columns('doctor_slots')}

    if 'capacity' not in existing_cols:
        op.add_column('doctor_slots', sa.Column('capacity', sa.Integer(), nullable=False, server_default='1'))
    if 'booked_count' not in existing_cols:
        op.add_column('doctor_slots', sa.Column('booked_count', sa.Integer(), nullable=False, server_default='0'))

    if 'is_booked' in existing_cols:
        op.execute("UPDATE doctor_slots SET booked_count = 1, capacity = 1 WHERE is_booked = true")
        op.drop_column('doctor_slots', 'is_booked')


def downgrade():
    op.add_column('doctor_slots', sa.Column('is_booked', sa.Boolean(), server_default=sa.false()))
    op.execute("UPDATE doctor_slots SET is_booked = (booked_count >= capacity)")
    op.drop_column('doctor_slots', 'booked_count')
    op.drop_column('doctor_slots', 'capacity')