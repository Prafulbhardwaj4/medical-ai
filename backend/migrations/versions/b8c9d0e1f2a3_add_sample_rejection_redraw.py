"""add sample rejection/redraw tracking + irreplaceable-sample flag"""
from alembic import op
import sqlalchemy as sa

revision = '953c74719cb5'
down_revision = 'a7b8c9d0e1f2'


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
    if 'test_orders' not in insp.get_table_names():
        op.create_table(
            'test_orders',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('consultation_id', sa.Integer(), sa.ForeignKey('consultations.id'), nullable=False),
            sa.Column('patient_id', sa.Integer(), sa.ForeignKey('patients.id'), nullable=False),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('test_id', sa.Integer(), sa.ForeignKey('test_catalog_items.id'), nullable=True),
            sa.Column('test_name', sa.String(), nullable=False),
            sa.Column('price', sa.Float(), nullable=False, server_default='0'),
            sa.Column('status', sa.String(), nullable=False, server_default='payment_pending'),
            sa.Column('paid_at', sa.DateTime(), nullable=True),
            sa.Column('collected_at', sa.DateTime(), nullable=True),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
    insp = sa.inspect(bind)

    item_cols = {c['name'] for c in insp.get_columns('test_catalog_items')}
    if 'is_irreplaceable_sample' not in item_cols:
        op.add_column('test_catalog_items', sa.Column('is_irreplaceable_sample', sa.Boolean(), nullable=False, server_default='false'))

    order_cols = {c['name'] for c in insp.get_columns('test_orders')}
    if 'rejection_reason' not in order_cols:
        op.add_column('test_orders', sa.Column('rejection_reason', sa.String(), nullable=True))
    if 'rejected_at' not in order_cols:
        op.add_column('test_orders', sa.Column('rejected_at', sa.DateTime(), nullable=True))
    if 'rejected_by' not in order_cols or 'redraw_of_order_id' not in order_cols:
        with op.batch_alter_table('test_orders') as batch_op:
            if 'rejected_by' not in order_cols:
                batch_op.add_column(sa.Column('rejected_by', sa.Integer(), nullable=True))
                batch_op.create_foreign_key('fk_test_orders_rejected_by', 'doctors', ['rejected_by'], ['id'])
            if 'redraw_of_order_id' not in order_cols:
                batch_op.add_column(sa.Column('redraw_of_order_id', sa.Integer(), nullable=True))
                batch_op.create_foreign_key('fk_test_orders_redraw_of_order_id', 'test_orders', ['redraw_of_order_id'], ['id'])
    if 'sample_condition_caveat' not in order_cols:
        op.add_column('test_orders', sa.Column('sample_condition_caveat', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('test_orders', 'sample_condition_caveat')
    with op.batch_alter_table('test_orders') as batch_op:
        batch_op.drop_constraint('fk_test_orders_redraw_of_order_id', type_='foreignkey')
        batch_op.drop_column('redraw_of_order_id')
        batch_op.drop_constraint('fk_test_orders_rejected_by', type_='foreignkey')
        batch_op.drop_column('rejected_by')
    op.drop_column('test_orders', 'rejected_at')
    op.drop_column('test_orders', 'rejection_reason')
    op.drop_column('test_catalog_items', 'is_irreplaceable_sample')