"""add radiology_snapshot_json to cross_hospital_referrals (item 1)"""
from alembic import op
import sqlalchemy as sa

revision = 'c9d8e7f6a5b4'
down_revision = 'v8w9x0y1z2a3'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('cross_hospital_referrals')}
    if 'radiology_snapshot_json' not in cols:
        op.add_column('cross_hospital_referrals', sa.Column('radiology_snapshot_json', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('cross_hospital_referrals', 'radiology_snapshot_json')