"""make suggestions.submitted_by nullable (patients have no doctors.id)

Revision ID: q9r0s1t2u3v4
Revises: p8q9r0s1t2u3
Create Date: 2026-09-20 00:00:00

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'q9r0s1t2u3v4'
down_revision: Union[str, Sequence[str], None] = 'p8q9r0s1t2u3'
branch_labels = None
depends_on = None

def upgrade() -> None:
    with op.batch_alter_table('suggestions') as batch_op:
        batch_op.alter_column('submitted_by', nullable=True)

def downgrade() -> None:
    with op.batch_alter_table('suggestions') as batch_op:
        batch_op.alter_column('submitted_by', nullable=False)