"""add completed_by column to test_orders"""
from alembic import op
import sqlalchemy as sa

revision = 's7t8u9v0w1x2'
down_revision = 'r6s7t8u9v0w1'

def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        with op.batch_alter_table('test_orders') as batch_op:
            batch_op.add_column(sa.Column('completed_by', sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                'fk_test_orders_completed_by_doctors',
                'doctors', ['completed_by'], ['id']
            )
    else:
        op.add_column('test_orders', sa.Column('completed_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True))

def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        with op.batch_alter_table('test_orders') as batch_op:
            batch_op.drop_constraint('fk_test_orders_completed_by_doctors', type_='foreignkey')
            batch_op.drop_column('completed_by')
    else:
        op.drop_column('test_orders', 'completed_by')