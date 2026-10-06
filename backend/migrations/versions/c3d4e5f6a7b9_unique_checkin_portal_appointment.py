"""unique checkins.portal_appointment_id: one token per online appointment (NULLs allowed)"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b9'
down_revision = 'b7c6d5e4f3a2'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    dupes = bind.execute(sa.text(
        "SELECT portal_appointment_id FROM checkins WHERE portal_appointment_id IS NOT NULL "
        "GROUP BY portal_appointment_id HAVING COUNT(*) > 1"
    )).fetchall()
    if dupes:
        raise RuntimeError(
            "Duplicate check-ins exist for portal_appointment_id(s) "
            + ", ".join(str(r[0]) for r in dupes)
            + ". Resolve them manually, then re-run."
        )
    insp = sa.inspect(bind)
    existing = {i['name'] for i in insp.get_indexes('checkins')}
    if 'uq_checkins_portal_appointment_id' not in existing:
        op.create_index('uq_checkins_portal_appointment_id', 'checkins', ['portal_appointment_id'], unique=True)


def downgrade():
    op.drop_index('uq_checkins_portal_appointment_id', table_name='checkins')