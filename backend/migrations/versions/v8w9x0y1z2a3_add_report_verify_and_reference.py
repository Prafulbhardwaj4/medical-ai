"""merge heads + add verify_hash/report_reference to test_orders and radiology_orders (items 1, 3)"""
from alembic import op
import sqlalchemy as sa

revision = 'v8w9x0y1z2a3'
down_revision = ('r0s1t2u3v4w5', 't3u4v5w6x7y8')
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    test_cols = {c['name'] for c in insp.get_columns('test_orders')}
    if 'verify_hash' not in test_cols:
        op.add_column('test_orders', sa.Column('verify_hash', sa.String(), nullable=True))
        op.create_index('ix_test_orders_verify_hash', 'test_orders', ['verify_hash'])
    if 'report_reference' not in test_cols:
        op.add_column('test_orders', sa.Column('report_reference', sa.String(), nullable=True))
        op.create_index('ix_test_orders_report_reference', 'test_orders', ['report_reference'])

    rad_cols = {c['name'] for c in insp.get_columns('radiology_orders')}
    if 'verify_hash' not in rad_cols:
        op.add_column('radiology_orders', sa.Column('verify_hash', sa.String(), nullable=True))
        op.create_index('ix_radiology_orders_verify_hash', 'radiology_orders', ['verify_hash'])
    if 'report_reference' not in rad_cols:
        op.add_column('radiology_orders', sa.Column('report_reference', sa.String(), nullable=True))
        op.create_index('ix_radiology_orders_report_reference', 'radiology_orders', ['report_reference'])


def downgrade():
    op.drop_index('ix_radiology_orders_report_reference', table_name='radiology_orders')
    op.drop_column('radiology_orders', 'report_reference')
    op.drop_index('ix_radiology_orders_verify_hash', table_name='radiology_orders')
    op.drop_column('radiology_orders', 'verify_hash')
    op.drop_index('ix_test_orders_report_reference', table_name='test_orders')
    op.drop_column('test_orders', 'report_reference')
    op.drop_index('ix_test_orders_verify_hash', table_name='test_orders')
    op.drop_column('test_orders', 'verify_hash')