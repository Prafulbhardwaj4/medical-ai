"""add doctor availability template and unavailability tables"""
from alembic import op
import sqlalchemy as sa

revision = 'd3e4f5a6b7c8'
down_revision = 'c2d3e4f5a6b7'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if 'doctor_availability_templates' not in existing_tables:
        op.create_table(
            'doctor_availability_templates',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('doctor_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False, unique=True),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('weekdays', sa.String(), nullable=False, server_default='[0,1,2,3,4,5]'),
            sa.Column('morning_times', sa.String(), nullable=False, server_default='[]'),
            sa.Column('afternoon_times', sa.String(), nullable=False, server_default='[]'),
            sa.Column('evening_times', sa.String(), nullable=False, server_default='[]'),
            sa.Column('capacity_mode', sa.String(), nullable=False, server_default='same'),
            sa.Column('capacity_same', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('capacity_morning', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('capacity_afternoon', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('capacity_evening', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
        )

    if 'doctor_unavailability' not in existing_tables:
        op.create_table(
            'doctor_unavailability',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('doctor_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('date', sa.Date(), nullable=False),
            sa.Column('reason', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.UniqueConstraint('doctor_id', 'date', name='uq_doctor_unavailable_date'),
        )
        op.create_index('ix_doctor_unavailability_date', 'doctor_unavailability', ['date'])


def downgrade():
    op.drop_table('doctor_unavailability')
    op.drop_table('doctor_availability_templates')