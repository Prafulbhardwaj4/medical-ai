"""checkin_consult_times: when the doctor pressed Consult and when the consultation was finished.

Two nullable columns, added only if missing. They feed the patient's "expected time" banner and the
doctor's average consultation length. Nothing is rewritten; downgrade does nothing on purpose.
"""
from alembic import op
import sqlalchemy as sa

revision = 'f4c2a7d19b36'
down_revision = 'e1a8c3d57f29'
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    if 'checkins' not in set(insp.get_table_names()):
        return
    existing = {c['name'] for c in insp.get_columns('checkins')}
    for name in ('consult_started_at', 'consult_finished_at'):
        if name not in existing:
            op.add_column('checkins', sa.Column(name, sa.DateTime(), nullable=True))


def downgrade():
    # Intentionally empty: removing the columns would lose the recorded consultation times.
    pass