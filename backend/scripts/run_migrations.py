"""Runs the database migrations once, as a release step (instead of at every app start).

    python scripts/run_migrations.py
    python scripts/run_migrations.py --database-url "postgresql://user:pass@host/db"

Use it with RUN_MIGRATIONS_ON_BOOT=false on the app. It takes the same database lock the app uses, so it is
safe even if an old instance is still starting. Exit code 0 on success, 1 on failure.
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


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    url = _db_url(argv)
    if url:
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        os.environ["DATABASE_URL"] = url  # before the app modules are imported
    from alembic import command as alembic_command
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from app.config import settings
    from app.database import engine
    from app.utils.boot import boot_lock

    print("Database:", engine.url.render_as_string(hide_password=True))
    if engine.dialect.name == "sqlite":
        print("SQLite (local dev): nothing to do, tables are built from the models.")
        return 0

    def current():
        with engine.connect() as conn:
            return ", ".join(sorted(MigrationContext.configure(conn).get_current_heads())) or "(none)"

    db_url = settings.DATABASE_URL
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    print("Before:", current())
    try:
        with boot_lock(engine, "migrations"):
            alembic_command.upgrade(cfg, "heads")
    except Exception as e:
        print(f"FAILED: the migration did not finish ({type(e).__name__}: {e}). Nothing further was applied.")
        return 1
    print("After: ", current())
    print("OK: migrations are up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())