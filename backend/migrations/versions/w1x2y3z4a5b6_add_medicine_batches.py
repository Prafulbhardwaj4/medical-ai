"""add medicine_batches table for expiry-dated stock tracking"""
from alembic import op
import sqlalchemy as sa

revision = 'w1x2y3z4a5b6'
down_revision = 'v0w1x2y3z4a5'

def upgrade():
    op.create_table(
        'medicine_batches',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('medicine_id', sa.Integer(), sa.ForeignKey('hospital_medicines.id'), nullable=False),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('batch_number', sa.String(), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('received_date', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )

def downgrade():
    op.drop_table('medicine_batches')