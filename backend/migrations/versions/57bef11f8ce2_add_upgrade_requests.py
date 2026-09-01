"""add upgrade_requests table

Revision ID: 57bef11f8ce2
Revises: 906b27734d11
Create Date: 2026-09-01
"""
from alembic import op
import sqlalchemy as sa

revision = '57bef11f8ce2'
down_revision = '906b27734d11'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'upgrade_requests' in insp.get_table_names():
        return
    op.create_table(
        'upgrade_requests',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('requested_by_id', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
        sa.Column('requested_tier', sa.String(), nullable=False),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('contact_name', sa.String(), nullable=False),
        sa.Column('contact_phone', sa.String(), nullable=False),
        sa.Column('contact_email', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='new'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table('upgrade_requests')