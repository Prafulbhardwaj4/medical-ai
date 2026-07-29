"""add opd_referrals table for OPD-level 'refer to Dr. Y'"""
from alembic import op
import sqlalchemy as sa

revision = 'z8d9e0f1a2b3'
down_revision = 'z7c8d9e0f1a2'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'opd_referrals' not in insp.get_table_names():
        op.create_table(
            'opd_referrals',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('patient_id', sa.Integer(), sa.ForeignKey('patients.id'), nullable=False),
            sa.Column('referring_doctor_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('referred_to_doctor_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('checkin_id', sa.Integer(), sa.ForeignKey('checkins.id'), nullable=True),
            sa.Column('note', sa.Text(), nullable=True),
            sa.Column('status', sa.String(), nullable=False, server_default='pending'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )


def downgrade():
    op.drop_table('opd_referrals')