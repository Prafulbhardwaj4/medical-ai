"""add admission_referrals table"""
from alembic import op
import sqlalchemy as sa

revision = 'n3o4p5q6r7s8'
down_revision = 'm2n3o4p5q6r7_doctor_uid'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'admission_referrals' not in insp.get_table_names():
        op.create_table(
            'admission_referrals',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('patient_id', sa.Integer(), sa.ForeignKey('patients.id'), nullable=False),
            sa.Column('referred_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('reason', sa.Text(), nullable=True),
            sa.Column('status', sa.String(), nullable=False, server_default='pending'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )


def downgrade():
    op.drop_table('admission_referrals')