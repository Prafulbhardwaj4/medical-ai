"""add test catalog table and recommended_test_ids"""
from alembic import op
import sqlalchemy as sa

revision = 'b3d7f420e816'
down_revision = 'a2c6d9f31b47'

def upgrade():
    op.create_table(
        'test_catalog_items',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('fee', sa.Float(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.add_column('consultations', sa.Column('recommended_test_ids', sa.Text(), nullable=True))

def downgrade():
    op.drop_column('consultations', 'recommended_test_ids')
    op.drop_table('test_catalog_items')