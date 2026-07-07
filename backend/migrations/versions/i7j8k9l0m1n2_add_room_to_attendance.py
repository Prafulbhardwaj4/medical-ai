"""add_room_number_to_attendance

Revision ID: i7j8k9l0m1n2
Revises: h6i7j8k9l0m1
Create Date: 2026-07-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'i7j8k9l0m1n2'
down_revision = 'h6i7j8k9l0m1'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('attendance_records', sa.Column('room_number', sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column('attendance_records', 'room_number')