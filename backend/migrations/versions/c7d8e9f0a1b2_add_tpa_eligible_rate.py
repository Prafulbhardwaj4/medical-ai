"""add TPA eligible daily rate for proportionate deduction calculation"""
from alembic import op
import sqlalchemy as sa

revision = '31fb003c8af6'
down_revision = 'b6c7d8e9f0a1'


def upgrade():
    bind = op.get_bind()
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
    if 'eligible_daily_rate' not in cols:
        op.add_column('admission_tpa_cases', sa.Column('eligible_daily_rate', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('admission_tpa_cases', 'eligible_daily_rate')