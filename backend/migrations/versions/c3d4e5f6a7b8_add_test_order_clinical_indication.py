"""add clinical_indication to test_orders"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'test_orders' not in insp.get_table_names():
        # test_orders is created by p4q5r6s7t8u9_add_test_orders.py, which
        # sits on a different branch that hasn't necessarily applied yet at
        # this point in the graph — create the base table here defensively
        # so nothing gets lost regardless of which branch runs first.
        # p4q5r6s7t8u9 itself is idempotent and will just no-op if it runs
        # after this.
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
    if 'clinical_indication' not in existing_cols:
        op.add_column('test_orders', sa.Column('clinical_indication', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('test_orders', 'clinical_indication')