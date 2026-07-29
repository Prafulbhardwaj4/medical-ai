"""add is_icu to admission_ward_types"""
from alembic import op
import sqlalchemy as sa

revision = 'y6z7a8b9c0d1'
down_revision = 'x5y6z7a8b9c0'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('admission_ward_types')}
    if 'is_icu' not in cols:
        op.add_column('admission_ward_types', sa.Column('is_icu', sa.Boolean(), nullable=False, server_default='false'))


def downgrade():
    op.drop_column('admission_ward_types', 'is_icu')