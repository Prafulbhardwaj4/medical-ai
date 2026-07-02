"""add receptionist role"""
from alembic import op

revision = 'd4e5f6a7b8c9'
down_revision = 'a8f3c2d1e9b4'

def upgrade():
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'receptionist'")

def downgrade():
    pass