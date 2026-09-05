"""add cross_hospital_referrals table + admission referral columns

Revision ID: a1b2c3d4e5f9
Revises: 6efe879ac2a9
Create Date: 2026-09-04
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f9'
down_revision = '6efe879ac2a9'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if 'cross_hospital_referrals' not in insp.get_table_names():
        op.create_table(
            'cross_hospital_referrals',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('chain_id', sa.Integer(), nullable=False, index=True),
            sa.Column('from_hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('to_hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('source_admission_id', sa.Integer(), sa.ForeignKey('admissions.id'), nullable=True),
            sa.Column('origin_patient_id', sa.Integer(), sa.ForeignKey('patients.id'), nullable=True),
            sa.Column('initiation_type', sa.String(), nullable=False, server_default='referral'),
            sa.Column('initiated_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('superseded_referral_id', sa.Integer(), sa.ForeignKey('cross_hospital_referrals.id'), nullable=True),
            sa.Column('patient_name', sa.String(), nullable=False),
            sa.Column('patient_age', sa.Integer(), nullable=True),
            sa.Column('patient_gender', sa.String(), nullable=True),
            sa.Column('clinical_note', sa.Text(), nullable=False),
            sa.Column('diagnosis_snapshot', sa.Text(), nullable=True),
            sa.Column('vitals_snapshot_json', sa.Text(), nullable=True),
            sa.Column('medicines_snapshot_json', sa.Text(), nullable=True),
            sa.Column('tests_snapshot_json', sa.Text(), nullable=True),
            sa.Column('progress_notes_snapshot_json', sa.Text(), nullable=True),
            sa.Column('status', sa.String(), nullable=False, server_default='pending'),
            sa.Column('acknowledged_at', sa.DateTime(), nullable=True),
            sa.Column('rejected_at', sa.DateTime(), nullable=True),
            sa.Column('rejected_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
            sa.Column('rejection_note', sa.Text(), nullable=True),
            sa.Column('departed_at', sa.DateTime(), nullable=True),
            sa.Column('admitted_at', sa.DateTime(), nullable=True),
            sa.Column('admitted_admission_id', sa.Integer(), sa.ForeignKey('admissions.id'), nullable=True),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )

    admission_cols = {c['name'] for c in insp.get_columns('admissions')}
    with op.batch_alter_table('admissions') as batch_op:
        if 'received_via_referral_id' not in admission_cols:
            batch_op.add_column(sa.Column(
                'received_via_referral_id', sa.Integer(),
                sa.ForeignKey('cross_hospital_referrals.id', name='fk_admissions_received_via_referral_id'),
                nullable=True,
            ))
        if 'pending_outbound_referral_id' not in admission_cols:
            batch_op.add_column(sa.Column(
                'pending_outbound_referral_id', sa.Integer(),
                sa.ForeignKey('cross_hospital_referrals.id', name='fk_admissions_pending_outbound_referral_id'),
                nullable=True,
            ))
        if 'referral_discharge_authorized' not in admission_cols:
            batch_op.add_column(sa.Column('referral_discharge_authorized', sa.Boolean(), nullable=False, server_default=sa.false()))

def downgrade():
    with op.batch_alter_table('admissions') as batch_op:
        batch_op.drop_column('referral_discharge_authorized')
        batch_op.drop_column('pending_outbound_referral_id')
        batch_op.drop_column('received_via_referral_id')
    op.drop_table('cross_hospital_referrals')