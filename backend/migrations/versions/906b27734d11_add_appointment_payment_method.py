"""add appointment payment_method and paid_at

Revision ID: 906b27734d11
Revises: a8b9c0d1e2f3
Create Date: 2026-09-01
"""
from alembic import op
import sqlalchemy as sa

revision = '906b27734d11'
down_revision = 'a8b9c0d1e2f3'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = {c['name'] for c in insp.get_columns('portal_appointments')}

    if 'payment_method' not in existing_cols:
        op.add_column('portal_appointments', sa.Column('payment_method', sa.String(), nullable=True))
    if 'paid_at' not in existing_cols:
        op.add_column('portal_appointments', sa.Column('paid_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('portal_appointments', 'paid_at')
    op.drop_column('portal_appointments', 'payment_method')