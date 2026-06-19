"""add vitals and blood group fields

Revision ID: a37829e97231
Revises: 1be428102a93
Create Date: 2026-06-13 11:06:00.495178

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a37829e97231'
down_revision: Union[str, Sequence[str], None] = '1be428102a93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass