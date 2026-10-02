"""patients.date_of_birth (optional)"""
from alembic import op
import sqlalchemy as sa

revision = 'a9b8c7d6e5f4'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    cols = {c['name'] for c in insp.get_columns('patients')}
    if 'date_of_birth' not in cols:
        op.add_column('patients', sa.Column('date_of_birth', sa.Date(), nullable=True))


def downgrade():
    op.drop_column('patients', 'date_of_birth')