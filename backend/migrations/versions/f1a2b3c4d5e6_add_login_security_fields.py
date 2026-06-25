"""add login security fields

Revision ID: f1a2b3c4d5e6
Revises: e627e67cb329
Create Date: 2026-06-25 00:00:00

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e627e67cb329'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('doctors', sa.Column('failed_login_attempts', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('doctors', sa.Column('locked_until', sa.DateTime(), nullable=True))

def downgrade() -> None:
    op.drop_column('doctors', 'locked_until')
    op.drop_column('doctors', 'failed_login_attempts')