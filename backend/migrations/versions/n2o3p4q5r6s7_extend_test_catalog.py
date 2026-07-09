"""extend test_catalog_items with category, reference ranges, unit, turnaround"""
from alembic import op
import sqlalchemy as sa

revision = 'n2o3p4q5r6s7'
down_revision = 'm1n2o3p4q5r6'

def upgrade():
    op.add_column('test_catalog_items', sa.Column('category', sa.String(), nullable=True))
    op.add_column('test_catalog_items', sa.Column('reference_range_male', sa.String(), nullable=True))
    op.add_column('test_catalog_items', sa.Column('reference_range_female', sa.String(), nullable=True))
    op.add_column('test_catalog_items', sa.Column('unit', sa.String(), nullable=True))
    op.add_column('test_catalog_items', sa.Column('turnaround_hours', sa.Integer(), nullable=True))

def downgrade():
    op.drop_column('test_catalog_items', 'turnaround_hours')
    op.drop_column('test_catalog_items', 'unit')
    op.drop_column('test_catalog_items', 'reference_range_female')
    op.drop_column('test_catalog_items', 'reference_range_male')
    op.drop_column('test_catalog_items', 'category')