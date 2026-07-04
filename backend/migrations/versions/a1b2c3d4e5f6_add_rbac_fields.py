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
    with op.batch_alter_table('doctors') as batch_op:
        batch_op.add_column(sa.Column('role', sa.String(), nullable=False, server_default='doctor'))
        batch_op.add_column(sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id', name='fk_doctors_hospital_id'), nullable=True))
        batch_op.add_column(sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'))
        batch_op.add_column(sa.Column('created_by', sa.Integer(), sa.ForeignKey('doctors.id', name='fk_doctors_created_by'), nullable=True))

def downgrade() -> None:
    with op.batch_alter_table('doctors') as batch_op:
        batch_op.drop_column('created_by')
        batch_op.drop_column('is_active')
        batch_op.drop_column('hospital_id')
        batch_op.drop_column('role')
    op.drop_index('ix_hospitals_hospital_code', table_name='hospitals')
    op.drop_table('hospitals')