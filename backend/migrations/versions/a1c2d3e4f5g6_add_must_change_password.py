"""add must_change_password to doctors

Revision ID: a1c2d3e4f5g6
Revises: a1b2c3d4e5f6
Create Date: 2026-09-11 00:00:00

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1c2d3e4f5g6'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # server_default='false' means EXISTING staff (pilot accounts already
    # in use) are untouched — they keep logging in as normal, no forced
    # change. Only accounts created after this ships get flagged True
    # (set explicitly in admin.py at creation).
    op.add_column('doctors', sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default='false'))

def downgrade() -> None:
    op.drop_column('doctors', 'must_change_password')