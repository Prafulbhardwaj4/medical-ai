"""add visit_group_id to checkins for multi-doctor visits"""
from alembic import op
import sqlalchemy as sa

revision = 'f2a3b4c5d6e7'
down_revision = 'b7c8d9e0f1a2'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = {c['name'] for c in insp.get_columns('checkins')}
    if 'visit_group_id' not in existing_cols:
        op.add_column('checkins', sa.Column('visit_group_id', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('checkins', 'visit_group_id')