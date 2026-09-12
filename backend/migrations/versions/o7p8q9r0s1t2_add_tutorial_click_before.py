"""add click_before to tutorial_steps

Revision ID: o7p8q9r0s1t2
Revises: n6o7p8q9r0s1
Create Date: 2026-09-12 00:00:00

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'o7p8q9r0s1t2'
down_revision: Union[str, Sequence[str], None] = 'n6o7p8q9r0s1'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('tutorial_steps', sa.Column('click_before', sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column('tutorial_steps', 'click_before')