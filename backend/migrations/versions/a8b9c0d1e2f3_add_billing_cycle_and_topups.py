"""add hospital billing cycle fields and ai_scribe_topups table"""
from alembic import op
import sqlalchemy as sa

revision = 'a8b9c0d1e2f3'
down_revision = 'f7a8b9c0d1e2'

def upgrade():
    op.add_column('hospitals', sa.Column('billing_cycle_start', sa.DateTime(), nullable=True))
    op.add_column('hospitals', sa.Column('ai_scribe_consultations_used', sa.Integer(), nullable=False, server_default='0'))

    op.create_table(
        'ai_scribe_topups',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('block_size', sa.Integer(), nullable=False),
        sa.Column('consultations_granted', sa.Integer(), nullable=False),
        sa.Column('consultations_used', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('price_paid', sa.Float(), nullable=False),
        sa.Column('payment_collected', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('purchased_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('purchased_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
    )

def downgrade():
    op.drop_table('ai_scribe_topups')
    op.drop_column('hospitals', 'ai_scribe_consultations_used')
    op.drop_column('hospitals', 'billing_cycle_start')