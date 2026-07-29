"""add refunds, day_end_closes, and invoices.amount_collected"""
from alembic import op
import sqlalchemy as sa

revision = 'x5y6z7a8b9c0'
down_revision = 'w4x5y6z7a8b9'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    inv_cols = {c['name'] for c in insp.get_columns('invoices')}
    if 'amount_collected' not in inv_cols:
        op.add_column('invoices', sa.Column('amount_collected', sa.Float(), nullable=True))

    if 'refunds' not in insp.get_table_names():
        op.create_table(
            'refunds',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('patient_id', sa.Integer(), sa.ForeignKey('patients.id'), nullable=False),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('source_type', sa.String(), nullable=False),
            sa.Column('source_id', sa.Integer(), nullable=True),
            sa.Column('amount', sa.Float(), nullable=False),
            sa.Column('channel', sa.String(), nullable=False),
            sa.Column('status', sa.String(), nullable=False, server_default='completed'),
            sa.Column('reason', sa.String(), nullable=True),
            sa.Column('processed_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('processed_at', sa.DateTime(), nullable=True),
        )

    if 'day_end_closes' not in insp.get_table_names():
        op.create_table(
            'day_end_closes',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('close_date', sa.Date(), nullable=False),
            sa.Column('system_cash', sa.Float(), nullable=False, server_default='0'),
            sa.Column('system_card', sa.Float(), nullable=False, server_default='0'),
            sa.Column('system_upi', sa.Float(), nullable=False, server_default='0'),
            sa.Column('counted_cash', sa.Float(), nullable=False, server_default='0'),
            sa.Column('counted_card', sa.Float(), nullable=False, server_default='0'),
            sa.Column('counted_upi', sa.Float(), nullable=False, server_default='0'),
            sa.Column('notes', sa.String(), nullable=True),
            sa.Column('closed_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('closed_at', sa.DateTime(), nullable=True),
        )


def downgrade():
    op.drop_table('day_end_closes')
    op.drop_table('refunds')
    op.drop_column('invoices', 'amount_collected')