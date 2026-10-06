"""patients.date_of_birth (optional)"""
from alembic import op
import sqlalchemy as sa

revision = 'c6b2e1a8d3f0'
down_revision = 'c5a1f0b7d2e9'
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    cols = {c['name'] for c in insp.get_columns('patients')}
    if 'date_of_birth' not in cols:
        op.add_column('patients', sa.Column('date_of_birth', sa.Date(), nullable=True))


def downgrade():
    op.drop_column('patients', 'date_of_birth')