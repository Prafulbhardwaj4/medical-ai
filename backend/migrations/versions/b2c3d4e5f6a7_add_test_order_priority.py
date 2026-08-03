"""add priority to test_orders"""
from alembic import op
import sqlalchemy as sa

revision = '9afe2b904daa'
down_revision = 'a1b2c3d4e5f6'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'test_orders' not in insp.get_table_names():
        # Same situation as clinical_indication's migration — test_orders
        # may not exist yet on this branch. Create it defensively.
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
    existing_cols = {c['name'] for c in insp.get_columns('test_orders')}
    if 'priority' not in existing_cols:
        op.add_column('test_orders', sa.Column('priority', sa.String(), nullable=False, server_default='routine'))


def downgrade():
    op.drop_column('test_orders', 'priority')