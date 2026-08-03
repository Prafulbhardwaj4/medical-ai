"""add verified_by/verified_at to test_orders for the verification-release gate"""
from alembic import op
import sqlalchemy as sa

revision = '75d1626a5fd7'
down_revision = 'f0a1b2c3d4e5'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_cols = {c['name'] for c in insp.get_columns('test_orders')}

    if 'verified_by' not in existing_cols:
        with op.batch_alter_table('test_orders') as batch_op:
            batch_op.add_column(sa.Column('verified_by', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_test_orders_verified_by', 'doctors', ['verified_by'], ['id'])
    if 'verified_at' not in existing_cols:
        op.add_column('test_orders', sa.Column('verified_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('test_orders', 'verified_at')
    with op.batch_alter_table('test_orders') as batch_op:
        batch_op.drop_constraint('fk_test_orders_verified_by', type_='foreignkey')
        batch_op.drop_column('verified_by')