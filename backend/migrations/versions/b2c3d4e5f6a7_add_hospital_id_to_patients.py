"""add hospital_id to patients

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-28 00:00:00
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('patients', sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=True))
    op.add_column('patients', sa.Column('created_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True))
    # Copy existing doctor_id to created_by
    op.execute("UPDATE patients SET created_by = doctor_id")
    # Set hospital_id from doctor's hospital
    op.execute("""
        UPDATE patients 
        SET hospital_id = doctors.hospital_id 
        FROM doctors 
        WHERE patients.doctor_id = doctors.id
    """)

def downgrade() -> None:
    op.drop_column('patients', 'created_by')
    op.drop_column('patients', 'hospital_id')