"""add_nurse_instructions_to_consultation

Revision ID: h6i7j8k9l0m1
Revises: g5h6i7j8k9l0
Create Date: 2026-07-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'h6i7j8k9l0m1'
down_revision = 'g5h6i7j8k9l0'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('consultations', sa.Column('nurse_instructions', sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column('consultations', 'nurse_instructions')