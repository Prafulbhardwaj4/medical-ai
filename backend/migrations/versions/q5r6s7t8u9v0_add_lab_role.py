"""add lab role"""
from alembic import op

revision = 'q5r6s7t8u9v0'
down_revision = 'p4q5r6s7t8u9'

def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'lab'")
    # SQLite stores role as a plain String column (no native enum type), so nothing to alter there.

def downgrade():
    pass