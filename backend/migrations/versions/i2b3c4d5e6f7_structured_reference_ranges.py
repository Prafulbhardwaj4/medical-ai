"""structured numeric reference ranges (low/high per sex) on test catalog items and parameters"""
import re
from alembic import op
import sqlalchemy as sa

revision = 'i2b3c4d5e6f7'
down_revision = 'g3b4c5d6e7f8'

_COLS = ('ref_low_male', 'ref_high_male', 'ref_low_female', 'ref_high_female')


def _bounds(text):
    if not text:
        return None
    c = str(text).replace(",", "").strip()
    low = c.lower()
    nums = re.findall(r"\d+\.?\d*", c)
    if c.startswith("<") or "less" in low or "upto" in low or "up to" in low:
        return (None, float(nums[0])) if nums else None
    if c.startswith(">") or "greater" in low or "above" in low:
        return (float(nums[0]), None) if nums else None
    parts = re.split(r"(?<=\d)\s*(?:-|–|—|\bto\b)\s*", c)
    if len(parts) == 2:
        lo = re.findall(r"\d+\.?\d*", parts[0])
        hi = re.findall(r"\d+\.?\d*", parts[1])
        if lo and hi:
            return float(lo[0]), float(hi[0])
    return None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table in ('test_catalog_items', 'test_catalog_parameters'):
        existing = {c['name'] for c in insp.get_columns(table)}
        for col in _COLS:
            if col not in existing:
                op.add_column(table, sa.Column(col, sa.Float(), nullable=True))
        # Back-fill from the free-text ranges already stored.
        rows = bind.execute(sa.text(f"SELECT id, reference_range_male, reference_range_female FROM {table}")).fetchall()
        for rid, rm, rf in rows:
            bm, bf = _bounds(rm), _bounds(rf)
            bind.execute(
                sa.text(f"UPDATE {table} SET ref_low_male=:a, ref_high_male=:b, ref_low_female=:c, ref_high_female=:d WHERE id=:i"),
                {"a": bm[0] if bm else None, "b": bm[1] if bm else None, "c": bf[0] if bf else None, "d": bf[1] if bf else None, "i": rid},
            )


def downgrade():
    for table in ('test_catalog_parameters', 'test_catalog_items'):
        for col in reversed(_COLS):
            op.drop_column(table, col)