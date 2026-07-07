"""add room_id fk to attendance_records"""
from alembic import op
import sqlalchemy as sa

revision = 'k9l0m1n2o3p4'
down_revision = 'j8k9l0m1n2o3'

def upgrade() -> None:
    with op.batch_alter_table('attendance_records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('room_id', sa.Integer(), nullable=True))

def downgrade():
    with op.batch_alter_table('attendance_records') as batch_op:
        batch_op.drop_column('room_id')