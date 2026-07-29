"""add admission_tpa_cases table"""
from alembic import op
import sqlalchemy as sa

revision = 'v3w4x5y6z7a8'
down_revision = 'u2v3w4x5y6z7'


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


def downgrade():
    op.drop_table('admission_tpa_cases')