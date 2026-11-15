"""Lists every table and column the code expects that the database does not have. Read only.

    python scripts/check_schema_drift.py
    python scripts/check_schema_drift.py --database-url "postgresql://user:pass@host/db"

Exit code 0: nothing is missing (once this is true on production, RUNTIME_SCHEMA_SYNC can be set to false).
Exit code 1: something is missing, or the database could not be read. Each missing item is printed.
It only compares table and column names; it never changes the database.
"""
import importlib
import os
import pkgutil
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)


def _db_url(argv):
    rest = list(argv)
    while rest:
        a = rest.pop(0)
        if a == "--database-url":
            return rest.pop(0) if rest else None
        if a.startswith("--database-url="):
            return a.split("=", 1)[1]
    return None


def load_models():
    """Imports every model module so Base.metadata knows every table."""
    import app.models as models_pkg
    for mod in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"app.models.{mod.name}")


def find_drift(engine, metadata):
    """Returns a sorted list of 'missing table x' / 'missing column x.y' for what the models have and the database lacks."""
    import sqlalchemy as sa
    insp = sa.inspect(engine)
    have = set(insp.get_table_names())
    problems = []
    for name in sorted(metadata.tables):
        table = metadata.tables[name]
        if name not in have:
            problems.append(f"missing table {name}")
            continue
        existing = {c["name"] for c in insp.get_columns(name)}
        for column in table.columns:
            if column.name not in existing:
                problems.append(f"missing column {name}.{column.name}")
    return problems


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    url = _db_url(argv)
    if url:
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        os.environ["DATABASE_URL"] = url  # before the app modules are imported
    from app.database import Base, engine
    load_models()
    print("Database:", engine.url.render_as_string(hide_password=True))
    try:
        problems = find_drift(engine, Base.metadata)
    except Exception as exc:  # unreachable database, bad credentials, ...
        print(f"PROBLEM: could not read the database ({type(exc).__name__}).")
        return 1
    if not problems:
        print("OK: the database has every table and column the code uses.")
        return 0
    for p in problems:
        print("  " + p)
    print(f"PROBLEM: {len(problems)} item(s) missing. Run: python scripts/run_migrations.py")
    return 1


if __name__ == "__main__":
    sys.exit(main())