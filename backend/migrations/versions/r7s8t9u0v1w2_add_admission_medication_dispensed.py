"""add dispensed_at/dispensed_by to admission_medication_orders"""
from alembic import op
import sqlalchemy as sa

revision = 'r7s8t9u0v1w2'
down_revision = 'q6r7s8t9u0v1'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('admission_medication_orders')}
    if 'dispensed_at' not in cols:
        op.add_column('admission_medication_orders', sa.Column('dispensed_at', sa.DateTime(), nullable=True))
    if 'dispensed_by' not in cols:
        op.add_column('admission_medication_orders', sa.Column('dispensed_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True))


def downgrade():
    op.drop_column('admission_medication_orders', 'dispensed_by')
    op.drop_column('admission_medication_orders', 'dispensed_at')