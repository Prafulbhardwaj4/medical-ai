"""add dispensed_at/dispensed_by to admission_medication_orders"""
from alembic import op
import sqlalchemy as sa

revision = 'r8t9u0v1w2x3'
down_revision = 'r7s8t9u0v1w2'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('admission_medication_orders')}
    with op.batch_alter_table('admission_medication_orders') as batch_op:
        if 'dispensed_at' not in cols:
            batch_op.add_column(sa.Column('dispensed_at', sa.DateTime(), nullable=True))
        if 'dispensed_by' not in cols:
            batch_op.add_column(sa.Column('dispensed_by', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_admission_medication_orders_dispensed_by', 'doctors', ['dispensed_by'], ['id'])


def downgrade():
    with op.batch_alter_table('admission_medication_orders') as batch_op:
        batch_op.drop_constraint('fk_admission_medication_orders_dispensed_by', type_='foreignkey')
        batch_op.drop_column('dispensed_by')
        batch_op.drop_column('dispensed_at')