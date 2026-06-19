"""add doctor registration number

Revision ID: 088eabd31363
Revises: 64868781b49f
Create Date: 2026-06-13 11:06:00.495178

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '088eabd31363'
down_revision: Union[str, Sequence[str], None] = '64868781b49f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass