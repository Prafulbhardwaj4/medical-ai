"""add aliases column to test_catalog_items"""
from alembic import op
import sqlalchemy as sa

revision = '2e2d0dcac31b'
down_revision = 'e2f3a4b5c6d7'

def upgrade():
    op.add_column('test_catalog_items', sa.Column('aliases', sa.Text(), nullable=True))

def downgrade():
    op.drop_column('test_catalog_items', 'aliases')