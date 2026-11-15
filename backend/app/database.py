import logging
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings

_log = logging.getLogger("medscribe")


def _database_url(url: str = None) -> str:
    """DATABASE_URL, with sslmode=require added for PostgreSQL when DB_REQUIRE_SSL=true.
    An sslmode already present in the URL is never overridden. SQLite is never touched."""
    url = url or settings.DATABASE_URL
    if "sqlite" in url:
        return url
    try:
        parsed = make_url(url)
    except Exception:
        return url
    has_sslmode = "sslmode" in (parsed.query or {})
    if settings.DB_REQUIRE_SSL and not has_sslmode:
        parsed = parsed.update_query_dict({"sslmode": "require"})
        return parsed.render_as_string(hide_password=False)
    if not settings.DB_REQUIRE_SSL and not has_sslmode:
        from app.config import _is_production
        if _is_production(settings):
            _log.warning("DATABASE_URL has no sslmode and DB_REQUIRE_SSL is not set: the database connection "
                         "may be unencrypted. Set DB_REQUIRE_SSL=true (or add ?sslmode=require to the URL).")
    return url


def _engine_kwargs(url: str = None) -> dict:
    url = url or settings.DATABASE_URL
    kwargs = {
        # Bound parameters (patient data) must never appear in error messages or logs.
        "hide_parameters": True,
    }
    if "sqlite" in url:
        kwargs["connect_args"] = {"check_same_thread": False}
        return kwargs
    kwargs.update(
        pool_pre_ping=True,                                   # drop dead connections instead of failing a request
        pool_recycle=max(60, int(settings.DB_POOL_RECYCLE_SECONDS)),
        pool_size=max(1, int(settings.DB_POOL_SIZE)),
        max_overflow=max(0, int(settings.DB_MAX_OVERFLOW)),
    )
    return kwargs


engine = create_engine(_database_url(), **_engine_kwargs())

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()