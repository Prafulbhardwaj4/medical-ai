"""add medicine_orders table"""
from alembic import op
import sqlalchemy as sa

revision = 'x2y3z4a5b6c7'
down_revision = 'w1x2y3z4a5b6'

def upgrade():
    op.create_table(
        'medicine_orders',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('consultation_id', sa.Integer(), sa.ForeignKey('consultations.id'), nullable=False),
        sa.Column('patient_id', sa.Integer(), sa.ForeignKey('patients.id'), nullable=False),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('catalog_medicine_id', sa.Integer(), sa.ForeignKey('hospital_medicines.id'), nullable=True),
        sa.Column('medicine_name', sa.String(), nullable=False),
        sa.Column('brand_name', sa.String(), nullable=True),
        sa.Column('dosage', sa.String(), nullable=True),
        sa.Column('frequency', sa.String(), nullable=True),
        sa.Column('duration', sa.String(), nullable=True),
        sa.Column('unit_price', sa.Float(), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=True),
        sa.Column('included', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(), nullable=False, server_default='advised'),
        # advised -> paid -> dispensed  (or stays 'advised' forever if excluded, never billed)
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.Column('dispensed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )

def downgrade():
    op.drop_table('medicine_orders')