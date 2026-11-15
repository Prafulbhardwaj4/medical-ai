"""day_end_closes_unique: one close per hospital per day.

Checks for existing duplicates FIRST. If any exist it stops with a message listing them and changes
nothing (it never deletes). Resolve them by hand (python scripts/list_duplicate_day_end_closes.py), then restart.

If other migrations were added after b9d2f6308e1c, point down_revision at the newest one instead.
"""
from alembic import op
import sqlalchemy as sa

revision = 'c4e8a1d7f203'
down_revision = 'b9d2f6308e1c'
branch_labels = None
depends_on = None

INDEX_NAME = 'uq_day_end_closes_hospital_date'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'day_end_closes' not in insp.get_table_names():
        return
    existing = {i['name'] for i in insp.get_indexes('day_end_closes')}
    existing |= {u['name'] for u in insp.get_unique_constraints('day_end_closes')}
    if INDEX_NAME in existing:
        return
    groups = bind.execute(sa.text(
        "SELECT hospital_id, close_date, COUNT(*) FROM day_end_closes "
        "GROUP BY hospital_id, close_date HAVING COUNT(*) > 1 ORDER BY hospital_id, close_date"
    )).fetchall()
    if groups:
        lines = []
        for hospital_id, close_date, count in groups:
            ids = [r[0] for r in bind.execute(
                sa.text("SELECT id FROM day_end_closes WHERE hospital_id = :h AND close_date = :d ORDER BY id"),
                {"h": hospital_id, "d": close_date}).fetchall()]
            lines.append(f"hospital {hospital_id}, day {close_date}: {count} rows (ids {', '.join(str(i) for i in ids)})")
        raise RuntimeError(
            "Cannot add the one-close-per-day rule because these days were closed more than once: "
            + "; ".join(lines)
            + ". Nothing was changed or deleted. Run `python scripts/list_duplicate_day_end_closes.py`, "
              "resolve them by hand, then restart.")
    op.create_index(INDEX_NAME, 'day_end_closes', ['hospital_id', 'close_date'], unique=True)


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if 'day_end_closes' in insp.get_table_names() and INDEX_NAME in {i['name'] for i in insp.get_indexes('day_end_closes')}:
        op.drop_index(INDEX_NAME, table_name='day_end_closes')