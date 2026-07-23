"""add sourced_outside flag to admission_medication_orders"""
from alembic import op
import sqlalchemy as sa

revision = 'k0l1m2n3o4p5'
down_revision = 'j9k0l1m2n3o4'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('admission_medication_orders')}
    if 'sourced_outside' not in cols:
        if bind.dialect.name == 'sqlite':
            with op.batch_alter_table('admission_medication_orders') as batch_op:
                batch_op.add_column(sa.Column('sourced_outside', sa.Boolean(), nullable=False, server_default=sa.false()))
        else:
            op.add_column('admission_medication_orders', sa.Column('sourced_outside', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        with op.batch_alter_table('admission_medication_orders') as batch_op:
            batch_op.drop_column('sourced_outside')
    else:
        op.drop_column('admission_medication_orders', 'sourced_outside')