"""add is_emergency_ward flag to admission_ward_types"""
from alembic import op
import sqlalchemy as sa

revision = '2785c745c6ac'
down_revision = 'b797251c9c71'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('admission_ward_types')}
    if 'is_emergency_ward' not in cols:
        op.add_column('admission_ward_types', sa.Column('is_emergency_ward', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('admission_ward_types', 'is_emergency_ward')