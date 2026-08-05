"""add manual_unit_price to admission_medication_orders"""
from alembic import op
import sqlalchemy as sa

revision = 'b9c8d7e6f5a4'
down_revision = 'a4b5c6d7e8f9'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('admission_medication_orders')}
    with op.batch_alter_table('admission_medication_orders') as batch_op:
        if 'manual_unit_price' not in cols:
            batch_op.add_column(sa.Column('manual_unit_price', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('admission_medication_orders') as batch_op:
        batch_op.drop_column('manual_unit_price')