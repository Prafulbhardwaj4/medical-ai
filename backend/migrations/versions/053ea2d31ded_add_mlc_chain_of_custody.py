"""add MLC sample flags and chain-of-custody table"""
from alembic import op
import sqlalchemy as sa

revision = '053ea2d31ded'
down_revision = 'b128263186b4'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    order_cols = {c['name'] for c in insp.get_columns('test_orders')}
    if 'is_mlc_sample' not in order_cols:
        op.add_column('test_orders', sa.Column('is_mlc_sample', sa.Boolean(), nullable=False, server_default='false'))
    if 'mlc_case_type' not in order_cols:
        op.add_column('test_orders', sa.Column('mlc_case_type', sa.String(), nullable=True))
    if 'mlc_reference_number' not in order_cols:
        op.add_column('test_orders', sa.Column('mlc_reference_number', sa.String(), nullable=True))

    existing_tables = set(insp.get_table_names())
    if 'mlc_chain_of_custody' not in existing_tables:
        op.create_table(
            'mlc_chain_of_custody',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('test_order_id', sa.Integer(), sa.ForeignKey('test_orders.id'), nullable=False),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('stage', sa.String(), nullable=False),
            sa.Column('handed_over_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
            sa.Column('handed_over_by_external_name', sa.String(), nullable=True),
            sa.Column('received_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True),
            sa.Column('received_by_external_name', sa.String(), nullable=True),
            sa.Column('seal_intact', sa.Boolean(), nullable=True),
            sa.Column('seal_number', sa.String(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('recorded_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=False),
            sa.Column('recorded_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_mlc_chain_of_custody_test_order_id', 'mlc_chain_of_custody', ['test_order_id'])


def downgrade():
    op.drop_index('ix_mlc_chain_of_custody_test_order_id', table_name='mlc_chain_of_custody')
    op.drop_table('mlc_chain_of_custody')
    op.drop_column('test_orders', 'mlc_reference_number')
    op.drop_column('test_orders', 'mlc_case_type')
    op.drop_column('test_orders', 'is_mlc_sample')