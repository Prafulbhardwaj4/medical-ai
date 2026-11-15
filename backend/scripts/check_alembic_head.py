"""Prints the migration the database is at versus the head(s) in the code. Read only.

    python scripts/check_alembic_head.py
    python scripts/check_alembic_head.py --database-url "postgresql://user:pass@host/db"

Exit code 0: database is at head (safe to set RUNTIME_SCHEMA_SYNC=false).
Exit code 1: behind, ahead, or more than one head in the code.
"""
import os
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


def script_directory():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "migrations"))
    return ScriptDirectory.from_config(cfg)


def compare(script, current_heads):
    """Returns (status, message). status is one of: ok, behind, ahead, multiple_heads."""
    heads = sorted(script.get_heads())
    current = sorted(current_heads)
    if len(heads) > 1:
        return "multiple_heads", f"the code has {len(heads)} heads ({', '.join(heads)}): create a merge migration"
    all_revs = {r.revision for r in script.walk_revisions()}
    unknown = [c for c in current if c not in all_revs]
    if unknown:
        return "ahead", f"the database is at {', '.join(unknown)}, which this code does not have (database is ahead of the code)"
    if current == heads:
        return "ok", "the database is at head"
    applied = set()
    for c in current:
        applied |= {r.revision for r in script.iterate_revisions(c, "base")}
    pending = [r for r in all_revs if r not in applied]
    return "behind", f"the database is behind by {len(pending)} migration(s)"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    url = _db_url(argv)
    if url:
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        os.environ["DATABASE_URL"] = url  # before the app modules are imported
    from alembic.runtime.migration import MigrationContext
    from app.database import engine
    print("Database:", engine.url.render_as_string(hide_password=True))
    script = script_directory()
    with engine.connect() as conn:
        current = sorted(MigrationContext.configure(conn).get_current_heads())
    print("Database is at:", ", ".join(current) or "(no alembic_version rows)")
    print("Code head(s):  ", ", ".join(sorted(script.get_heads())))
    if engine.dialect.name == "sqlite":
        print("SQLite (local dev) builds its tables from the models; Alembic is not used here.")
        return 0
    status, message = compare(script, current)
    print(("OK: " if status == "ok" else "PROBLEM: ") + message)
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())