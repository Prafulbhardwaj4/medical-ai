"""add pharmacy role"""
from alembic import op

revision = 't8u9v0w1x2y3'
down_revision = 's7t8u9v0w1x2'

def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'pharmacy'")
    # SQLite stores role as a plain String column (no native enum type), so nothing to alter there.

def downgrade():
    pass