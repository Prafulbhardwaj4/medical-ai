"""add notifiable_diseases table, test catalog link, and per-order flag"""
from alembic import op
import sqlalchemy as sa

revision = '0957a2f94adb'
down_revision = '8c5de10471cc'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    existing_tables = set(insp.get_table_names())
    if 'notifiable_diseases' not in existing_tables:
        op.create_table(
            'notifiable_diseases',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('hospital_id', sa.Integer(), sa.ForeignKey('hospitals.id'), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )

    item_cols = {c['name'] for c in insp.get_columns('test_catalog_items')}
    if 'notifiable_disease_id' not in item_cols:
        # SQLite can't ALTER TABLE ADD COLUMN with an inline FK constraint
        # directly — batch mode does the copy-and-move it needs; on other
        # dialects (Postgres) it's just a normal ALTER, so this is safe
        # everywhere, not just SQLite.
        with op.batch_alter_table('test_catalog_items') as batch_op:
            batch_op.add_column(sa.Column('notifiable_disease_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_test_catalog_items_notifiable_disease_id', 'notifiable_diseases', ['notifiable_disease_id'], ['id'])

    order_cols = {c['name'] for c in insp.get_columns('test_orders')}
    if 'is_idsp_notifiable' not in order_cols:
        op.add_column('test_orders', sa.Column('is_idsp_notifiable', sa.Boolean(), nullable=False, server_default='false'))


def downgrade():
    op.drop_column('test_orders', 'is_idsp_notifiable')
    with op.batch_alter_table('test_catalog_items') as batch_op:
        batch_op.drop_column('notifiable_disease_id')
    op.drop_table('notifiable_diseases')