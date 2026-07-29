"""add opd_charges table"""
from alembic import op
import sqlalchemy as sa

revision = 't1u2v3w4x5y6'
down_revision = 's8t9u0v1w2x3'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'opd_charges' not in insp.get_table_names():
        op.create_table(
            'opd_charges',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('checkin_id', sa.Integer(), sa.ForeignKey('checkins.id'), nullable=False),
            sa.Column('patient_id', sa.Integer(), sa.ForeignKey('patients.id'), nullable=False),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('description', sa.String(), nullable=False),
            sa.Column('amount', sa.Float(), nullable=False),
            sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('added_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('status', sa.String(), nullable=False, server_default='payment_pending'),
            sa.Column('payment_method', sa.String(), nullable=True),
            sa.Column('paid_at', sa.DateTime(), nullable=True),
            sa.Column('charged_at', sa.DateTime(), nullable=True),
        )


def downgrade():
    op.drop_table('opd_charges')