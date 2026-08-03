"""add discharge order timestamp for discharge-delay tracking"""
from alembic import op
import sqlalchemy as sa

revision = 'f4a5b6c7d8e9_delay'
down_revision = 'e3f4a5b6c7d8'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('admissions')}

    if 'discharge_order_at' not in cols:
        op.add_column('admissions', sa.Column('discharge_order_at', sa.DateTime(), nullable=True))
    if 'discharge_ordered_by' not in cols:
        with op.batch_alter_table('admissions') as batch_op:
            batch_op.add_column(sa.Column('discharge_ordered_by', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_admissions_discharge_ordered_by', 'doctors', ['discharge_ordered_by'], ['id'])


def downgrade():
    with op.batch_alter_table('admissions') as batch_op:
        batch_op.drop_constraint('fk_admissions_discharge_ordered_by', type_='foreignkey')
        batch_op.drop_column('discharge_ordered_by')
    op.drop_column('admissions', 'discharge_order_at')