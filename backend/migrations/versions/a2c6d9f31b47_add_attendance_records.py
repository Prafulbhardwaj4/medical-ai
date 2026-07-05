"""add attendance_records table"""
from alembic import op
import sqlalchemy as sa

revision = 'a2c6d9f31b47'
down_revision = 'f4b8e21a9c05'

def upgrade():
    op.create_table(
        'attendance_records',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('doctor_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('date', sa.Date(), nullable=False, index=True),
        sa.Column('status', sa.String(), nullable=False, server_default='present'),
        sa.Column('marked_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('doctor_id', 'date', name='uq_attendance_doctor_date'),
    )

def downgrade():
    op.drop_table('attendance_records')