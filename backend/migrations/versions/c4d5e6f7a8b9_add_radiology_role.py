"""add radiology role"""
from alembic import op
import sqlalchemy as sa

revision = 'c4d5e6f7a8b9'
down_revision = 'b5c6d7e8f9a2'

def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        result = bind.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'userrole'")).first()
        if result:
            op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'radiology'")
    # role is a plain String column app-wide; no native enum type to alter on fresh DBs.

def downgrade():
    pass