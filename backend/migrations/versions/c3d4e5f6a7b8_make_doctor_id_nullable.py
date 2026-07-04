"""make doctor_id nullable in patients

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-29 00:00:00
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None

def upgrade() -> None:
    with op.batch_alter_table('patients') as batch_op:
        batch_op.alter_column('doctor_id', nullable=True)

def downgrade() -> None:
    with op.batch_alter_table('patients') as batch_op:
        batch_op.alter_column('doctor_id', nullable=False)