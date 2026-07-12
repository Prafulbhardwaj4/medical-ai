"""add billed_quantity and substitute_for_id to medicine_orders"""
from alembic import op
import sqlalchemy as sa

revision = 'e2f3a4b5c6d7'
down_revision = 'd0e1f2a3b4c5'

def _existing_columns(bind):
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns("medicine_orders")}

def upgrade():
    bind = op.get_bind()
    existing = _existing_columns(bind)

    if "billed_quantity" not in existing:
        op.add_column('medicine_orders', sa.Column('billed_quantity', sa.Integer(), nullable=True))

    if "substitute_for_id" not in existing:
        if bind.dialect.name == 'sqlite':
            with op.batch_alter_table('medicine_orders') as batch_op:
                batch_op.add_column(sa.Column('substitute_for_id', sa.Integer(), nullable=True))
                batch_op.create_foreign_key(
                    'fk_medicine_orders_substitute_for_id_medicine_orders',
                    'medicine_orders', ['substitute_for_id'], ['id']
                )
        else:
            op.add_column('medicine_orders', sa.Column('substitute_for_id', sa.Integer(), sa.ForeignKey('medicine_orders.id'), nullable=True))

def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        with op.batch_alter_table('medicine_orders') as batch_op:
            batch_op.drop_constraint('fk_medicine_orders_substitute_for_id_medicine_orders', type_='foreignkey')
            batch_op.drop_column('substitute_for_id')
    else:
        op.drop_column('medicine_orders', 'substitute_for_id')

    op.drop_column('medicine_orders', 'billed_quantity')