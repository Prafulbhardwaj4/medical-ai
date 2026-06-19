"""initial schema

Revision ID: 4514dae22e96
Revises: 
Create Date: 2026-06-13 11:06:00.495178

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4514dae22e96'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('doctors',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('phone', sa.String(), nullable=False),
        sa.Column('specialization', sa.String(), nullable=False),
        sa.Column('registration_number', sa.String(), nullable=True),
        sa.Column('clinic_name', sa.String(), nullable=False),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_doctors_id', 'doctors', ['id'])
    op.create_index('ix_doctors_email', 'doctors', ['email'], unique=True)

    op.create_table('patients',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('patient_uid', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('phone', sa.String(), nullable=False),
        sa.Column('age', sa.Integer(), nullable=False),
        sa.Column('blood_group', sa.String(), nullable=True),
        sa.Column('gender', sa.String(), nullable=False),
        sa.Column('doctor_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['doctor_id'], ['doctors.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_patients_id', 'patients', ['id'])
    op.create_index('ix_patients_patient_uid', 'patients', ['patient_uid'], unique=True)

    op.create_table('consultations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token_number', sa.String(), nullable=True),
        sa.Column('patient_id', sa.Integer(), nullable=False),
        sa.Column('doctor_id', sa.Integer(), nullable=False),
        sa.Column('raw_transcript', sa.Text(), nullable=True),
        sa.Column('chief_complaint', sa.Text(), nullable=True),
        sa.Column('diagnosis', sa.Text(), nullable=True),
        sa.Column('medicines', sa.Text(), nullable=True),
        sa.Column('tests', sa.Text(), nullable=True),
        sa.Column('advice', sa.Text(), nullable=True),
        sa.Column('followup', sa.Text(), nullable=True),
        sa.Column('vitals', sa.Text(), nullable=True),
        sa.Column('is_voided', sa.Boolean(), nullable=True),
        sa.Column('has_pending_tests', sa.Boolean(), nullable=True),
        sa.Column('pdf_path', sa.String(), nullable=True),
        sa.Column('whatsapp_status', sa.String(), nullable=True),
        sa.Column('verify_hash', sa.String(), nullable=True),
        sa.Column('is_dispensed', sa.Boolean(), nullable=True),
        sa.Column('dispensed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['doctor_id'], ['doctors.id']),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_consultations_id', 'consultations', ['id'])
    op.create_index('ix_consultations_token_number', 'consultations', ['token_number'], unique=True)
    op.create_index('ix_consultations_verify_hash', 'consultations', ['verify_hash'], unique=True)


def downgrade() -> None:
    op.drop_table('consultations')
    op.drop_table('patients')
    op.drop_table('doctors')