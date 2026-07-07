"""add_room_number_to_doctors

Revision ID: g5h6i7j8k9l0
Revises: f4b8e21a9c05
Create Date: 2026-07-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'g5h6i7j8k9l0'
down_revision = 'f4b8e21a9c05'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('doctors', sa.Column('room_number', sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column('doctors', 'room_number')