"""add blood group field

Revision ID: 896cbc579dc8
Revises: a37829e97231
Create Date: 2026-06-13 11:06:00.495178

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '896cbc579dc8'
down_revision: Union[str, Sequence[str], None] = 'a37829e97231'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass