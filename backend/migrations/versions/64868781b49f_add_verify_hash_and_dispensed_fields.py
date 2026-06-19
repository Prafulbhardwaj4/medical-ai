"""add verify hash and dispensed fields

Revision ID: 64868781b49f
Revises: 4514dae22e96
Create Date: 2026-06-13 11:06:00.495178

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '64868781b49f'
down_revision: Union[str, Sequence[str], None] = '4514dae22e96'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass