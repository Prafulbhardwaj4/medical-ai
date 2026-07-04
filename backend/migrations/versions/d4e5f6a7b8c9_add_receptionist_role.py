"""add receptionist role"""
from alembic import op

revision = 'd4e5f6a7b8c9'
down_revision = 'a8f3c2d1e9b4'

def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'receptionist'")
    # SQLite stores role as a plain String column (no native enum type), so nothing to alter there.

def downgrade():
    pass