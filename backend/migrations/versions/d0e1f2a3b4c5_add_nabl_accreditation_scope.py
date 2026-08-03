"""add is_nabl_accredited to test_catalog_items"""
from alembic import op
import sqlalchemy as sa

revision = 'd0e1f2a3b4c5'
down_revision = 'c9d0e1f2a3b4'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = {c['name'] for c in insp.get_columns('test_catalog_items')}
    if 'is_nabl_accredited' not in existing_cols:
        op.add_column('test_catalog_items', sa.Column('is_nabl_accredited', sa.Boolean(), nullable=False, server_default='false'))


def downgrade():
    op.drop_column('test_catalog_items', 'is_nabl_accredited')