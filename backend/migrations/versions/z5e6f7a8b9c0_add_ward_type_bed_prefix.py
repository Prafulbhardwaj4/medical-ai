"""add bed_prefix to admission_ward_types, backfilled from current names"""
from alembic import op
import sqlalchemy as sa
import re


def _initials(name):
    words = [w for w in re.split(r"\s+", (name or "").strip()) if w]
    if len(words) > 1:
        return "".join(w[0] for w in words).upper()[:4]
    return re.sub(r"[^A-Za-z]", "", name or "")[:3].upper() or "WD"


revision = 'z5e6f7a8b9c0'
down_revision = 'z4d5e6f7a8b9'  # add_admission_balance_collected — adjust to your real current head (multiple heads still unmerged, see prior notes)


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c['name'] for c in insp.get_columns('admission_ward_types')}
    if 'bed_prefix' not in cols:
        op.add_column('admission_ward_types', sa.Column('bed_prefix', sa.String(), nullable=True))
    # Backfill using each ward type's CURRENT name — this only fixes the bug
    # going forward. Any ward already renamed since beds were assigned needs
    # a manual one-time fix: find its actual occupied bed_number prefixes in
    # the admissions table and set bed_prefix to match those, not the new name.
    result = bind.execute(sa.text("SELECT id, name FROM admission_ward_types WHERE bed_prefix IS NULL"))
    for row in result:
        bind.execute(
            sa.text("UPDATE admission_ward_types SET bed_prefix = :prefix WHERE id = :id"),
            {"prefix": _initials(row.name), "id": row.id}
        )


def downgrade():
    op.drop_column('admission_ward_types', 'bed_prefix')