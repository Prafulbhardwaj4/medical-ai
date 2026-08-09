"""merge heads — suggestion follow-up/replies branch + prior tip

Revision ID: 8c66c6640c00
Revises: ce935d25bc88, z3c4d5e6f7a8
Create Date: 2026-08-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8c66c6640c00'
down_revision: Union[str, Sequence[str], None] = ('ce935d25bc88', 'z3c4d5e6f7a8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass