"""add vitals field

Revision ID: 1be428102a93
Revises: 088eabd31363
Create Date: 2026-06-13 11:06:00.495178

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '1be428102a93'
down_revision: Union[str, Sequence[str], None] = '088eabd31363'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass