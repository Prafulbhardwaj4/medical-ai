"""add included flag to test_orders"""
from alembic import op
import sqlalchemy as sa

revision = 'y3z4a5b6c7d8'
down_revision = 'x2y3z4a5b6c7'

def upgrade():
    op.add_column('test_orders', sa.Column('included', sa.Boolean(), nullable=False, server_default='1'))

def downgrade():
    op.drop_column('test_orders', 'included')