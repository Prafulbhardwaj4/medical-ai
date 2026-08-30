"""add recommended/ordered radiology fields to consultations"""
from alembic import op
import sqlalchemy as sa

revision = 'e6f7a8b9c0d1'
down_revision = 'd5e6f7a8b9c0'

def upgrade():
    op.add_column('consultations', sa.Column('recommended_radiology_template_ids', sa.Text(), nullable=True))
    op.add_column('consultations', sa.Column('ordered_radiology', sa.Text(), nullable=True))

def downgrade():
    op.drop_column('consultations', 'ordered_radiology')
    op.drop_column('consultations', 'recommended_radiology_template_ids')