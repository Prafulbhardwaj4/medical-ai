"""add is_read_by_staff to suggestion_replies"""
from alembic import op
import sqlalchemy as sa

revision = 'a4d7e2c9f6b1'
down_revision = 'f3a9c1d4e8b2'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('suggestion_replies')}
    if 'is_read_by_staff' not in cols:
        op.add_column('suggestion_replies', sa.Column('is_read_by_staff', sa.Boolean(), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('suggestion_replies', 'is_read_by_staff')