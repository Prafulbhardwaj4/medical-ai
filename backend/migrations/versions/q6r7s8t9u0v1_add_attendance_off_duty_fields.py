"""add expected_off_duty_at and auto_marked to attendance_records"""
from alembic import op
import sqlalchemy as sa

revision = 'q6r7s8t9u0v1'
down_revision = 'p5q6r7s8t9u0'

def upgrade():
    op.add_column('attendance_records', sa.Column('expected_off_duty_at', sa.DateTime(), nullable=True))
    op.add_column('attendance_records', sa.Column('auto_marked', sa.Integer(), nullable=False, server_default='0'))

def downgrade():
    op.drop_column('attendance_records', 'auto_marked')
    op.drop_column('attendance_records', 'expected_off_duty_at')