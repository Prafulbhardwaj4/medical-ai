"""add lab role"""
from alembic import op
import sqlalchemy as sa

revision = 'q5r6s7t8u9v0'
down_revision = 'p4q5r6s7t8u9'

def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        result = bind.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'userrole'")).first()
        if result:
            op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'lab'")
    # role is a plain String column app-wide; no native enum type to alter on fresh DBs.

def downgrade():
    pass