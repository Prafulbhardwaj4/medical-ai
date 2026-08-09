"""merge heads — suggestions branch + self-verified-flag/checkins-table branch

Revision ID: ce935d25bc88
Revises: a2b3c4d5e6f7, f1c2d3e4f5a6
Create Date: 2026-08-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ce935d25bc88'
down_revision: Union[str, Sequence[str], None] = ('a2b3c4d5e6f7', 'f1c2d3e4f5a6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass