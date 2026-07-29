"""add admission deposits, topup requests, and ward-type default deposit"""
from alembic import op
import sqlalchemy as sa

revision = 'u2v3w4x5y6z7'
down_revision = 't1u2v3w4x5y6'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    wt_cols = {c['name'] for c in insp.get_columns('admission_ward_types')}
    if 'default_deposit' not in wt_cols:
        op.add_column('admission_ward_types', sa.Column('default_deposit', sa.Float(), nullable=False, server_default='0'))

    if 'admission_deposits' not in insp.get_table_names():
        op.create_table(
            'admission_deposits',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('admission_id', sa.Integer(), sa.ForeignKey('admissions.id'), nullable=False),
            sa.Column('amount', sa.Float(), nullable=False),
            sa.Column('payment_method', sa.String(), nullable=False),
            sa.Column('note', sa.String(), nullable=True),
            sa.Column('collected_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('collected_at', sa.DateTime(), nullable=True),
        )

    if 'admission_deposit_topup_requests' not in insp.get_table_names():
        op.create_table(
            'admission_deposit_topup_requests',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('admission_id', sa.Integer(), sa.ForeignKey('admissions.id'), nullable=False),
            sa.Column('requested_amount', sa.Float(), nullable=False),
            sa.Column('reason', sa.String(), nullable=True),
            sa.Column('status', sa.String(), nullable=False, server_default='pending'),
            sa.Column('requested_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('requested_at', sa.DateTime(), nullable=True),
            sa.Column('deposit_id', sa.Integer(), sa.ForeignKey('admission_deposits.id'), nullable=True),
            sa.Column('resolved_at', sa.DateTime(), nullable=True),
        )


def downgrade():
    op.drop_table('admission_deposit_topup_requests')
    op.drop_table('admission_deposits')
    op.drop_column('admission_ward_types', 'default_deposit')