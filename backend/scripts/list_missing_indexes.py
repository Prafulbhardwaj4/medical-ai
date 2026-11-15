"""Read-only index review: lists foreign-key columns and common filter columns that have no index
starting with that column. Changes nothing.

    python scripts/list_missing_indexes.py
    python scripts/list_missing_indexes.py --database-url "postgresql://user:pass@host/db"

The CREATE INDEX lines it prints are suggestions to review, not something to paste blindly.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FILTER_COLUMNS = {
    "hospital_id", "patient_id", "doctor_id", "status", "created_at", "visit_date", "requested_time",
    "due_at", "token_hash", "verify_hash", "public_token", "url_token",
}


def _db_url(argv):
    rest = list(argv)
    while rest:
        a = rest.pop(0)
        if a == "--database-url":
            return rest.pop(0) if rest else None
        if a.startswith("--database-url="):
            return a.split("=", 1)[1]
    return None


def find_missing(insp):
    """Returns {"foreign_keys": [(table, column)], "filters": [(table, column)]}."""
    out = {"foreign_keys": [], "filters": []}
    for table in sorted(insp.get_table_names()):
        leading = set()
        for ix in insp.get_indexes(table):
            cols = [c for c in ix.get("column_names", []) if c]
            if cols:
                leading.add(cols[0])
        for uc in insp.get_unique_constraints(table):
            if uc.get("column_names"):
                leading.add(uc["column_names"][0])
        pk = insp.get_pk_constraint(table).get("constrained_columns") or []
        if pk:
            leading.add(pk[0])
        fk_cols = {c for fk in insp.get_foreign_keys(table) for c in fk["constrained_columns"]}
        columns = {c["name"] for c in insp.get_columns(table)}
        for col in sorted(fk_cols):
            if col not in leading:
                out["foreign_keys"].append((table, col))
        for col in sorted((columns & FILTER_COLUMNS) - fk_cols):
            if col not in leading:
                out["filters"].append((table, col))
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    url = _db_url(argv)
    if url:
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        os.environ["DATABASE_URL"] = url  # before the app modules are imported
    from sqlalchemy import inspect
    from app.database import engine
    print("Database:", engine.url.render_as_string(hide_password=True))
    missing = find_missing(inspect(engine))
    for title, rows in (("Foreign key columns with no index", missing["foreign_keys"]),
                        ("Common filter columns with no index", missing["filters"])):
        print(f"\n{title}: {len(rows)}")
        for table, col in rows:
            print(f"  {table}.{col}    -- CREATE INDEX ix_{table}_{col} ON {table} ({col});")
    if not (missing["foreign_keys"] or missing["filters"]):
        print("\nOK: nothing to add.")
    return 0


if __name__ == "__main__":
    sys.exit(main())