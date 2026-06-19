"""add is voided field

Revision ID: e627e67cb329
Revises: 896cbc579dc8
Create Date: 2026-06-13 11:06:00.495178

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'e627e67cb329'
down_revision: Union[str, Sequence[str], None] = '896cbc579dc8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass