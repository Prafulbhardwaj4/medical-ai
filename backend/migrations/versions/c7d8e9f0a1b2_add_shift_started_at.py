"""add shift_started_at to attendance_records"""
from alembic import op
import sqlalchemy as sa

revision = 'c7d8e9f0a1b2'
down_revision = 'b6c7d8e9f0a1'

def upgrade():
    op.add_column('attendance_records', sa.Column('shift_started_at', sa.DateTime(), nullable=True))

def downgrade():
    op.drop_column('attendance_records', 'shift_started_at')