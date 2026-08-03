"""add ward type category presets"""
from alembic import op
import sqlalchemy as sa

revision = '992110a8d25b'
down_revision = 'f4a5b6c7d8e9_delay'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('admission_ward_types')}
    if 'category' not in cols:
        op.add_column('admission_ward_types', sa.Column('category', sa.String(), nullable=False, server_default='general'))


def downgrade():
    op.drop_column('admission_ward_types', 'category')