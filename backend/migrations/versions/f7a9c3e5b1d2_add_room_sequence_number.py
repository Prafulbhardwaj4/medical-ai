"""add_room_sequence_number

Revision ID: f7a9c3e5b1d2
Revises: 2e2d0dcac31b
Create Date: 2026-07-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'f7a9c3e5b1d2'
down_revision = '2e2d0dcac31b'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('rooms', sa.Column('sequence_number', sa.Integer(), nullable=True))

def downgrade() -> None:
    op.drop_column('rooms', 'sequence_number')