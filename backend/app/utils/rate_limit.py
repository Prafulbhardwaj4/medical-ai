import logging
import threading
import time
from slowapi import Limiter
from starlette.requests import Request
from app.config import settings, _is_production


def client_ip(request: Request) -> str:
    """Real client IP behind a reverse proxy. Takes the Nth entry from the
    right of X-Forwarded-For (N = settings.TRUSTED_PROXY_HOPS) because the
    proxy appends the address it actually saw; anything to the left is
    client-supplied and spoofable."""
    hops = settings.TRUSTED_PROXY_HOPS
    if hops > 0:
        parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    return request.client.host if request.client else "unknown"


# One shared limiter for the whole app (previously six separate instances).
# Storage is Redis when REDIS_URL is set (shared by every worker, survives restarts, falls back to
# memory if Redis is down); otherwise in-memory (per worker process, reset on restart).
limiter = Limiter(
    key_func=client_ip,
    storage_uri=settings.REDIS_URL or "memory://",
    in_memory_fallback_enabled=bool(settings.REDIS_URL),
)

if not settings.REDIS_URL and _is_production(settings):
    logging.getLogger("medscribe").warning(
        "REDIS_URL is not set: rate limits and login-failure counters are kept in memory, "
        "reset on every restart and are counted separately per worker process. Set REDIS_URL.")

_redis_client = None


def _redis():
    """Shared Redis connection for the failure counters, or None when REDIS_URL is not set / unusable."""
    global _redis_client
    if not settings.REDIS_URL:
        return None
    if _redis_client is None:
        try:
            import redis
            _redis_client = redis.Redis.from_url(
                settings.REDIS_URL, socket_timeout=1, socket_connect_timeout=1, decode_responses=True)
        except Exception:
            logging.getLogger("medscribe").exception("Redis could not be opened; using in-memory failure counters")
            return None
    return _redis_client


class FailureThrottle:
    """Tiny per-key failed-attempt counter (e.g. per phone number), used where
    there is no per-account lockout. In-memory, per worker."""

    _instances = 0
    _all = []

    def __init__(self, max_failures: int, window_seconds: int, name: str = ""):
        self.max_failures = max_failures
        self.window = window_seconds
        FailureThrottle._instances += 1
        # Each throttle gets its own Redis key prefix (same code => same order => same names in every worker).
        self.name = name or f"t{FailureThrottle._instances}"
        self._data = {}
        self._lock = threading.Lock()
        FailureThrottle._all.append(self)

    @classmethod
    def reset_all_memory(cls) -> None:
        """For tests: clears the in-memory counters of every throttle."""
        for t in cls._all:
            with t._lock:
                t._data.clear()

    def _live(self, key):
        now = time.time()
        return [t for t in self._data.get(key, []) if now - t < self.window]

    def _rkey(self, key) -> str:
        return f"medscribe:ft:{self.name}:{key}"

    def _redis_count(self, r, key, add: bool) -> int:
        import uuid
        now = time.time()
        k = self._rkey(key)
        pipe = r.pipeline()
        pipe.zremrangebyscore(k, 0, now - self.window)
        if add:
            pipe.zadd(k, {f"{now}:{uuid.uuid4().hex[:8]}": now})
            pipe.expire(k, int(self.window) + 5)
        pipe.zcard(k)
        return int(pipe.execute()[-1])

    def is_blocked(self, key: str) -> bool:
        r = _redis()
        if r is not None:
            try:
                return self._redis_count(r, key, add=False) >= self.max_failures
            except Exception:
                logging.getLogger("medscribe").exception("Redis failure counter unavailable; using memory")
        with self._lock:
            hits = self._live(key)
            self._data[key] = hits
            return len(hits) >= self.max_failures

    def record_failure(self, key: str) -> None:
        r = _redis()
        if r is not None:
            try:
                self._redis_count(r, key, add=True)
                return
            except Exception:
                logging.getLogger("medscribe").exception("Redis failure counter unavailable; using memory")
        with self._lock:
            hits = self._live(key)
            hits.append(time.time())
            self._data[key] = hits

    def reset(self, key: str) -> None:
        r = _redis()
        if r is not None:
            try:
                r.delete(self._rkey(key))
            except Exception:
                logging.getLogger("medscribe").exception("Redis failure counter unavailable; using memory")
        with self._lock:
            self._data.pop(key, None)