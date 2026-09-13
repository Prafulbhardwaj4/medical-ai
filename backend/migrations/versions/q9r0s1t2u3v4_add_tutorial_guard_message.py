"""add guard_message to tutorial_steps

Revision ID: q9r0s1t2u3v4
Revises: p8q9r0s1t2u3
Create Date: 2026-09-13 00:00:00

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'q9r0s1t2u3v4'
down_revision: Union[str, Sequence[str], None] = 'p8q9r0s1t2u3'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('tutorial_steps', sa.Column('guard_message', sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column('tutorial_steps', 'guard_message')