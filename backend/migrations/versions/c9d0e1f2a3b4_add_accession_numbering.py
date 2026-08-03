"""add accession_number/accessioned_at to test_orders"""
from alembic import op
import sqlalchemy as sa

revision = 'c9d0e1f2a3b4'
down_revision = 'b8c9d0e1f2a3'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = {c['name'] for c in insp.get_columns('test_orders')}
    if 'accession_number' not in existing_cols:
        op.add_column('test_orders', sa.Column('accession_number', sa.String(), nullable=True))
        op.create_index('ix_test_orders_accession_number', 'test_orders', ['accession_number'])
    if 'accessioned_at' not in existing_cols:
        op.add_column('test_orders', sa.Column('accessioned_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('test_orders', 'accessioned_at')
    op.drop_index('ix_test_orders_accession_number', table_name='test_orders')
    op.drop_column('test_orders', 'accession_number')