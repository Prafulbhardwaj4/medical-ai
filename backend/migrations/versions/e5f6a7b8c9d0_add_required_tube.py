"""add required_tube to test_catalog_items"""
from alembic import op
import sqlalchemy as sa

revision = '2b9b79bb37d4'
down_revision = 'd4e5f6a7b8c9'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'test_catalog_items' not in insp.get_table_names():
        op.create_table(
            'test_catalog_items',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('fee', sa.Float(), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        insp = sa.inspect(bind)
    existing_cols = {c['name'] for c in insp.get_columns('test_catalog_items')}
    if 'required_tube' not in existing_cols:
        op.add_column('test_catalog_items', sa.Column('required_tube', sa.String(), nullable=True))


def downgrade():
    op.drop_column('test_catalog_items', 'required_tube')