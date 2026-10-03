"""subscription_payments: one row per confirmed Renew (hospital, tier, amount, period, collected_by)"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c0'
down_revision = 'c3d4e5f6a7b9'
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    if 'subscription_payments' not in insp.get_table_names():
        op.create_table(
            'subscription_payments',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('tier', sa.String(), nullable=False),
            sa.Column('billing_period', sa.String(), nullable=False, server_default='monthly'),
            sa.Column('amount', sa.Float(), nullable=False),
            sa.Column('period_start', sa.DateTime(), nullable=False),
            sa.Column('period_end', sa.DateTime(), nullable=False),
            sa.Column('collected_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
            sa.Column('note', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_subscription_payments_hospital_id', 'subscription_payments', ['hospital_id'])


def downgrade():
    op.drop_index('ix_subscription_payments_hospital_id', table_name='subscription_payments')
    op.drop_table('subscription_payments')