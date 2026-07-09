"""add test_orders table"""
from alembic import op
import sqlalchemy as sa

revision = 'p4q5r6s7t8u9'
down_revision = 'o3p4q5r6s7t8'

def upgrade():
    op.create_table(
        'test_orders',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('consultation_id', sa.Integer(), sa.ForeignKey('consultations.id'), nullable=False),
        sa.Column('patient_id', sa.Integer(), sa.ForeignKey('patients.id'), nullable=False),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('test_id', sa.Integer(), sa.ForeignKey('test_catalog_items.id'), nullable=True),
        sa.Column('test_name', sa.String(), nullable=False),
        sa.Column('price', sa.Float(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(), nullable=False, server_default='payment_pending'),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.Column('collected_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )

def downgrade():
    op.drop_table('test_orders')