"""Prints every (hospital, day) that has more than one day_end_closes row. Read only: it deletes nothing.

    python scripts/list_duplicate_day_end_closes.py
    python scripts/list_duplicate_day_end_closes.py --database-url "postgresql://user:pass@host/db"

Run it BEFORE deploying the migration c4e8a1d7f203 (one close per hospital per day). Resolve each group by hand,
for example keep the row reception counted by hand and delete the auto-closed one. Exit code 1 if duplicates
exist, 0 if there are none.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _db_url(argv):
    rest = list(argv[1:])
    while rest:
        a = rest.pop(0)
        if a == "--database-url":
            return rest.pop(0) if rest else None
        if a.startswith("--database-url="):
            return a.split("=", 1)[1]
    return None


_URL = _db_url(sys.argv)
if _URL:
    if _URL.startswith("postgres://"):
        _URL = "postgresql://" + _URL[len("postgres://"):]
    os.environ["DATABASE_URL"] = _URL  # must be set before the app modules below are imported

from sqlalchemy import text  # noqa: E402


def find_duplicates(conn):
    """Returns [{hospital_id, close_date, rows: [{id, auto_closed, counted_cash, closed_at}]}]."""
    groups = conn.execute(text(
        "SELECT hospital_id, close_date FROM day_end_closes "
        "GROUP BY hospital_id, close_date HAVING COUNT(*) > 1 ORDER BY hospital_id, close_date")).fetchall()
    out = []
    for hospital_id, close_date in groups:
        rows = conn.execute(text(
            "SELECT id, auto_closed, counted_cash, closed_at FROM day_end_closes "
            "WHERE hospital_id = :h AND close_date = :d ORDER BY id"), {"h": hospital_id, "d": close_date}).fetchall()
        out.append({"hospital_id": hospital_id, "close_date": close_date,
                    "rows": [{"id": r[0], "auto_closed": r[1], "counted_cash": r[2], "closed_at": r[3]} for r in rows]})
    return out


def main():
    from app.database import engine
    print("Database:", engine.url.render_as_string(hide_password=True))
    with engine.connect() as conn:
        dups = find_duplicates(conn)
    if not dups:
        print("OK: no day was closed more than once.")
        return 0
    print(f"{len(dups)} day(s) closed more than once:")
    for g in dups:
        print(f"  hospital {g['hospital_id']}, day {g['close_date']}:")
        for r in g["rows"]:
            kind = "auto-closed" if r["auto_closed"] else "counted by hand"
            print(f"    id={r['id']}  {kind}  counted_cash={r['counted_cash']}  closed_at={r['closed_at']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())