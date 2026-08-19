"""add TPA settlement phase fields"""
from alembic import op
import sqlalchemy as sa

revision = '3cd6611fc018'
down_revision = 'a5b6c7d8e9f0'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if 'admissions' not in insp.get_table_names():
        # admissions is created by e4f5a6b7c8d9_add_admissions.py, which
        # sits on a different branch that isn't guaranteed to have applied
        # yet at this point in the graph. SQLite never caught this (it
        # doesn't enforce FK targets at CREATE TABLE time), but Postgres
        # does — create the base table here defensively so this doesn't
        # depend on branch-interleaving order. e4f5a6b7c8d9 itself already
        # checks 'if admissions not in existing_tables' so it just no-ops
        # if it runs after this.
        op.create_table(
            'admissions',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('patient_id', sa.Integer(), sa.ForeignKey('patients.id'), nullable=False),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('admitting_doctor_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('ward', sa.String(), nullable=False),
            sa.Column('bed_number', sa.String(), nullable=False),
            sa.Column('diagnosis', sa.Text(), nullable=True),
            sa.Column('daily_room_charge', sa.Float(), nullable=False, server_default='0'),
            sa.Column('status', sa.String(), nullable=False, server_default='admitted'),
            sa.Column('admission_date', sa.DateTime(), nullable=False),
            sa.Column('discharge_date', sa.DateTime(), nullable=True),
            sa.Column('discharge_summary', sa.Text(), nullable=True),
            sa.Column('discharge_invoice_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        insp = sa.inspect(bind)

    if 'admission_tpa_cases' not in insp.get_table_names():
        op.create_table(
            'admission_tpa_cases',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('admission_id', sa.Integer(), sa.ForeignKey('admissions.id'), nullable=False),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('insurer_name', sa.String(), nullable=False),
            sa.Column('policy_number', sa.String(), nullable=True),
            sa.Column('status', sa.String(), nullable=False, server_default='pending'),
            sa.Column('authorized_amount', sa.Float(), nullable=True),
            sa.Column('room_category_eligibility', sa.String(), nullable=True),
            sa.Column('copay_notes', sa.Text(), nullable=True),
            sa.Column('query_notes', sa.Text(), nullable=True),
            sa.Column('created_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.Column('resolved_at', sa.DateTime(), nullable=True),
        )
        insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('admission_tpa_cases')}

    if 'settlement_status' not in cols:
        op.add_column('admission_tpa_cases', sa.Column('settlement_status', sa.String(), nullable=True))
    if 'claim_submitted_amount' not in cols:
        op.add_column('admission_tpa_cases', sa.Column('claim_submitted_amount', sa.Float(), nullable=True))
    if 'claim_submitted_at' not in cols:
        op.add_column('admission_tpa_cases', sa.Column('claim_submitted_at', sa.DateTime(), nullable=True))
    if 'settled_amount' not in cols:
        op.add_column('admission_tpa_cases', sa.Column('settled_amount', sa.Float(), nullable=True))
    if 'settled_at' not in cols:
        op.add_column('admission_tpa_cases', sa.Column('settled_at', sa.DateTime(), nullable=True))
    if 'settlement_notes' not in cols:
        op.add_column('admission_tpa_cases', sa.Column('settlement_notes', sa.Text(), nullable=True))


def downgrade():
    for col in ('settlement_notes', 'settled_at', 'settled_amount', 'claim_submitted_at', 'claim_submitted_amount', 'settlement_status'):
        op.drop_column('admission_tpa_cases', col)