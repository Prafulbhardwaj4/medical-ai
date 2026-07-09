"""add hospital medicines table"""
from alembic import op
import sqlalchemy as sa

revision = 'm1n2o3p4q5r6'
down_revision = 'l0m1n2o3p4q5'

def upgrade():
    op.create_table(
        'hospital_medicines',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('generic_name', sa.String(), nullable=False),
        sa.Column('brand_names', sa.Text(), nullable=True),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('dosage_forms', sa.String(), nullable=True),
        sa.Column('schedule', sa.String(), nullable=False, server_default='otc'),
        sa.Column('price', sa.Float(), nullable=True),
        sa.Column('stock_quantity', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )

def downgrade():
    op.drop_table('hospital_medicines')