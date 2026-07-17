"""add_hospital_phone_and_logo

Revision ID: d3f6a1b2c9e4
Revises: f7a9c3e5b1d2
Create Date: 2026-07-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'd3f6a1b2c9e4'
down_revision = 'f7a9c3e5b1d2'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('hospitals', sa.Column('phone', sa.String(), nullable=True))
    op.add_column('hospitals', sa.Column('logo_base64', sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column('hospitals', 'logo_base64')
    op.drop_column('hospitals', 'phone')