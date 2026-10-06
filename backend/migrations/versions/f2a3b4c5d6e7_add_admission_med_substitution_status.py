"""admission medication orders: substitution_status"""
from alembic import op
import sqlalchemy as sa

revision = 'h1a2b3c4d5e6'
down_revision = 'a7d4e1c2b9f0'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('admission_medication_orders')}
    if 'substitution_status' not in cols:
        op.add_column('admission_medication_orders', sa.Column('substitution_status', sa.String(), nullable=True))


def downgrade():
    op.drop_column('admission_medication_orders', 'substitution_status')