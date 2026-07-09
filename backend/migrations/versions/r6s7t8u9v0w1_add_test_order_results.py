"""add result_data column to test_orders"""
from alembic import op
import sqlalchemy as sa

revision = 'r6s7t8u9v0w1'
down_revision = 'q5r6s7t8u9v0'

def upgrade():
    op.add_column('test_orders', sa.Column('result_data', sa.Text(), nullable=True))

def downgrade():
    op.drop_column('test_orders', 'result_data')