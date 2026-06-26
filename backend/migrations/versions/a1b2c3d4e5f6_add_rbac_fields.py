"""add rbac fields

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-06-26 00:00:00

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Create hospitals table
    op.create_table(
        'hospitals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('address', sa.String(), nullable=True),
        sa.Column('city', sa.String(), nullable=True),
        sa.Column('state', sa.String(), nullable=True),
        sa.Column('hospital_code', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('hospital_code', name='uq_hospital_code')
    )
    op.create_index('ix_hospitals_hospital_code', 'hospitals', ['hospital_code'])

    # Add new columns to doctors
    op.add_column('doctors', sa.Column('role', sa.String(), nullable=False, server_default='doctor'))
    op.add_column('doctors', sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=True))
    op.add_column('doctors', sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'))
    op.add_column('doctors', sa.Column('created_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True))

def downgrade() -> None:
    op.drop_column('doctors', 'created_by')
    op.drop_column('doctors', 'is_active')
    op.drop_column('doctors', 'hospital_id')
    op.drop_column('doctors', 'role')
    op.drop_index('ix_hospitals_hospital_code', table_name='hospitals')
    op.drop_table('hospitals')