"""add receptionist role"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'a8f3c2d1e9b4'

def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        result = bind.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'userrole'")).first()
        if result:
            op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'receptionist'")
    # role is a plain String column app-wide; no native enum type to alter on fresh DBs.

def downgrade():
    pass