"""add low_stock_threshold to hospital_medicines"""
from alembic import op
import sqlalchemy as sa

revision = 'a5b6c7d8e9f0'
down_revision = 'z4a5b6c7d8e9'

def upgrade():
    op.add_column('hospital_medicines', sa.Column('low_stock_threshold', sa.Integer(), nullable=False, server_default='25'))

def downgrade():
    op.drop_column('hospital_medicines', 'low_stock_threshold')