"""add rooms table"""
from alembic import op
import sqlalchemy as sa

revision = 'j8k9l0m1n2o3'
down_revision = 'i7j8k9l0m1n2'

def upgrade():
    op.create_table(
        'rooms',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
    )

def downgrade():
    op.drop_table('rooms')