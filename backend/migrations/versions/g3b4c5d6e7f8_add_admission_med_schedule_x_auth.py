"""admission medication orders: Schedule X repeat authorization fields"""
from alembic import op
import sqlalchemy as sa

revision = 'g3b4c5d6e7f8'
down_revision = 'h1a2b3c4d5e6' 

def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('admission_medication_orders')}
    if 'repeat_auth_status' not in cols:
        op.add_column('admission_medication_orders', sa.Column('repeat_auth_status', sa.String(), nullable=True))
    if 'repeat_authorized_by' not in cols:
        op.add_column('admission_medication_orders', sa.Column('repeat_authorized_by', sa.Integer(), sa.ForeignKey('doctors.id'), nullable=True))
    if 'repeat_authorized_at' not in cols:
        op.add_column('admission_medication_orders', sa.Column('repeat_authorized_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('admission_medication_orders', 'repeat_authorized_at')
    op.drop_column('admission_medication_orders', 'repeat_authorized_by')
    op.drop_column('admission_medication_orders', 'repeat_auth_status')