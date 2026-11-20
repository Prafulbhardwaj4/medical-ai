"""hospital_internal_notes: one private note box per hospital for the Super Admin.

One nullable text column, added only if missing. Nothing is rewritten; downgrade does nothing on purpose.
"""
from alembic import op
import sqlalchemy as sa

revision = '0784b41ab01b'
down_revision = 'f4c2a7d19b36'
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    if 'hospitals' not in set(insp.get_table_names()):
        return
    existing = {c['name'] for c in insp.get_columns('hospitals')}
    if 'internal_notes' not in existing:
        op.add_column('hospitals', sa.Column('internal_notes', sa.Text(), nullable=True))


def downgrade():
    # Intentionally empty: removing the column would lose the owner's notes.
    pass