"""add pharmacy role"""
from alembic import op
import sqlalchemy as sa

revision = 't8u9v0w1x2y3'
down_revision = 's7t8u9v0w1x2'

def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        result = bind.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'userrole'")).first()
        if result:
            op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'pharmacy'")
    # role is a plain String column app-wide; no native enum type to alter on fresh DBs.

def downgrade():
    pass