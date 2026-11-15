"""Start-up helpers: environment detection, refusal of dev flags in production,
Postgres advisory locks (boot lock for migrations/seeding, leader lock for the scheduler)."""
import contextlib
import hashlib
import logging
import os
import sys
import time

from sqlalchemy import text

from app.config import settings, _is_production

log = logging.getLogger("medscribe")


def explicit_production() -> bool:
    return bool(os.getenv("RENDER")) or os.getenv("ENVIRONMENT", "").lower() == "production"


def detect_environment() -> str:
    if os.getenv("RENDER"):
        return "production (RENDER is set)"
    if os.getenv("ENVIRONMENT", "").lower() == "production":
        return "production (ENVIRONMENT=production)"
    if _is_production(settings):
        return "production-like (non-SQLite database, but neither RENDER nor ENVIRONMENT=production is set)"
    return "development"


def _reload_requested() -> bool:
    if "--reload" in " ".join(sys.argv).lower():
        return True
    return os.getenv("UVICORN_RELOAD", "").strip().lower() in ("1", "true", "yes")


def check_runtime_flags() -> None:
    """Logs the detected environment and the boot switches. Refuses to start with --reload in production."""
    log.info("Environment: %s", detect_environment())
    log.info(
        "Boot switches: RUN_MIGRATIONS_ON_BOOT=%s RUNTIME_SCHEMA_SYNC=%s SCHEDULER_ENABLED=%s "
        "SEED_TUTORIAL_ON_BOOT=%s MASTER_CATALOG_AUTOLOAD_ON_BOOT=%s DAY_END_CATCHUP_ON_BOOT=%s",
        settings.RUN_MIGRATIONS_ON_BOOT, settings.RUNTIME_SCHEMA_SYNC, settings.SCHEDULER_ENABLED,
        settings.SEED_TUTORIAL_ON_BOOT, settings.MASTER_CATALOG_AUTOLOAD_ON_BOOT, settings.DAY_END_CATCHUP_ON_BOOT,
    )
    if _reload_requested():
        if explicit_production():
            raise RuntimeError(
                "Refusing to start: the server was started with --reload (a development flag) in production. "
                "Remove it from the start command.")
        if _is_production(settings):
            log.warning("The server was started with --reload against a non-SQLite database. "
                        "Never use --reload in production.")


class _SampleRequest:
    def __init__(self, forwarded_for: str):
        self.headers = {"x-forwarded-for": forwarded_for}
        self.client = None


def log_proxy_settings() -> None:
    """Prints the proxy hop count and the client IP the rate limiter would pick for a sample request
    that passed through that many trusted proxies. The sample client must come out as 198.51.100.23."""
    from app.utils.rate_limit import client_ip
    hops = settings.TRUSTED_PROXY_HOPS
    chain = ["198.51.100.23"] + [f"10.0.0.{i}" for i in range(1, max(hops, 1))]
    picked = client_ip(_SampleRequest(", ".join(chain)))
    log.info("TRUSTED_PROXY_HOPS=%s: for the sample forwarded chain [%s] the rate limiter would use client IP %s "
             "(expected 198.51.100.23 when the hop count matches the real proxy chain).",
             hops, ", ".join(chain), picked)
    if hops == 0 and _is_production(settings):
        log.warning("TRUSTED_PROXY_HOPS=0 in production: every client is seen as the proxy address, "
                    "so rate limits and lockouts would apply to everyone at once.")


def _key(name: str) -> int:
    digest = hashlib.sha256(f"medscribe:{name}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def _is_pg(engine) -> bool:
    return engine.dialect.name == "postgresql"


def _autocommit_connection(engine):
    return engine.connect().execution_options(isolation_level="AUTOCOMMIT")


@contextlib.contextmanager
def boot_lock(engine, name: str, timeout: int = None):
    """Blocks until this process holds the named Postgres advisory lock, so only one instance at a time
    runs migrations or seeding at boot. No-op on SQLite. Always released, even on errors."""
    if not _is_pg(engine):
        yield
        return
    timeout = settings.BOOT_LOCK_TIMEOUT_SECONDS if timeout is None else timeout
    key = _key("boot:" + name)
    conn = _autocommit_connection(engine)
    try:
        deadline = time.time() + timeout
        announced = False
        while not conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar():
            if not announced:
                log.info("Another instance is running the '%s' boot step; waiting for it.", name)
                announced = True
            if time.time() > deadline:
                raise RuntimeError(f"Could not get the '{name}' boot lock within {timeout} seconds")
            time.sleep(1)
        try:
            yield
        finally:
            try:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
            except Exception:
                log.exception("Could not release the '%s' boot lock; closing its connection", name)
                conn.invalidate()
    finally:
        conn.close()


class LeaderLock:
    """Session-level advisory lock held for the life of the process by exactly one instance
    (the scheduler leader). The lock disappears by itself when that instance's database connection ends."""

    def __init__(self, engine, name: str):
        self.engine = engine
        self.name = name
        self.key = _key("leader:" + name)
        self.conn = None

    def try_acquire(self) -> bool:
        if not _is_pg(self.engine):
            return True
        conn = None
        try:
            conn = _autocommit_connection(self.engine)
            if conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": self.key}).scalar():
                self.conn = conn
                return True
        except Exception:
            log.exception("Leader election for '%s' failed", self.name)
        if conn is not None:
            conn.close()
        return False

    def still_held(self) -> bool:
        if self.conn is None:
            return not _is_pg(self.engine)
        try:
            self.conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def release(self) -> None:
        conn, self.conn = self.conn, None
        if conn is None:
            return
        try:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": self.key})
            conn.close()
        except Exception:
            try:
                conn.invalidate()
                conn.close()
            except Exception:
                pass