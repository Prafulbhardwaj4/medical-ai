"""add ordered_tests column to consultations"""
from alembic import op
import sqlalchemy as sa

revision = 'o3p4q5r6s7t8'
down_revision = 'n2o3p4q5r6s7'

def upgrade():
    op.add_column('consultations', sa.Column('ordered_tests', sa.Text(), nullable=True))

def downgrade():
    op.drop_column('consultations', 'ordered_tests')