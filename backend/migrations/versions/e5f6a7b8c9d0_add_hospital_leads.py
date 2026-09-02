"""add hospital_leads table

Revision ID: e5f6a7b8c9d0
Revises: 57bef11f8ce2
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f6a7b8c9d0'
down_revision = '57bef11f8ce2'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'hospital_leads' in insp.get_table_names():
        return
    op.create_table(
        'hospital_leads',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('patient_account_id', sa.Integer(), sa.ForeignKey('patient_accounts.id'), nullable=False),
        sa.Column('contact_phone', sa.String(), nullable=False),
        sa.Column('state', sa.String(), nullable=False),
        sa.Column('city', sa.String(), nullable=False),
        sa.Column('hospital_name', sa.String(), nullable=False),
        sa.Column('location', sa.String(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='new'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table('hospital_leads')