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
    with op.batch_alter_table('patients') as batch_op:
        batch_op.add_column(sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id', name='fk_patients_hospital_id'), nullable=True))
        batch_op.add_column(sa.Column('created_by', sa.Integer(), sa.ForeignKey('doctors.id', name='fk_patients_created_by'), nullable=True))
    # Copy existing doctor_id to created_by
    op.execute("UPDATE patients SET created_by = doctor_id")
    # Set hospital_id from doctor's hospital
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        op.execute("""
            UPDATE patients
            SET hospital_id = (SELECT doctors.hospital_id FROM doctors WHERE doctors.id = patients.doctor_id)
            WHERE EXISTS (SELECT 1 FROM doctors WHERE doctors.id = patients.doctor_id)
        """)
    else:
        op.execute("""
            UPDATE patients 
            SET hospital_id = doctors.hospital_id 
            FROM doctors 
            WHERE patients.doctor_id = doctors.id
        """)

def downgrade() -> None:
    with op.batch_alter_table('patients') as batch_op:
        batch_op.drop_column('created_by')
        batch_op.drop_column('hospital_id')