"""add strength column to hospital_medicines"""
from alembic import op
import sqlalchemy as sa

revision = 'v0w1x2y3z4a5'
down_revision = 'u9v0w1x2y3z4'

def upgrade():
    op.add_column('hospital_medicines', sa.Column('strength', sa.String(), nullable=True))

def downgrade():
    op.drop_column('hospital_medicines', 'strength')