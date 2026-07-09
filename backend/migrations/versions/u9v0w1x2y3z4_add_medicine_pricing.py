"""add pricing fields to hospital_medicines: pack_size, price_per_pack, billing_mode, gst_percent"""
from alembic import op
import sqlalchemy as sa

revision = 'u9v0w1x2y3z4'
down_revision = 't8u9v0w1x2y3'

def upgrade():
    op.add_column('hospital_medicines', sa.Column('pack_size', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('hospital_medicines', sa.Column('price_per_pack', sa.Float(), nullable=True))
    op.add_column('hospital_medicines', sa.Column('billing_mode', sa.String(), nullable=False, server_default='per_unit'))
    op.add_column('hospital_medicines', sa.Column('gst_percent', sa.Float(), nullable=True))

def downgrade():
    op.drop_column('hospital_medicines', 'gst_percent')
    op.drop_column('hospital_medicines', 'billing_mode')
    op.drop_column('hospital_medicines', 'price_per_pack')
    op.drop_column('hospital_medicines', 'pack_size')