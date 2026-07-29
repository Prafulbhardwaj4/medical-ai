"""add attendance_coverage table for nurse/assistant ward+doctor multi-select"""
from alembic import op
import sqlalchemy as sa

revision = 'r7s8t9u0v1w2'
down_revision = 'q6r7s8t9u0v1'

def upgrade():
    op.create_table(
        'attendance_coverage',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('attendance_record_id', sa.Integer(), sa.ForeignKey('attendance_records.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('ward_type_id', sa.Integer(), sa.ForeignKey('admission_ward_types.id'), nullable=True),
        sa.Column('doctor_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
    )

def downgrade():
    op.drop_table('attendance_coverage')