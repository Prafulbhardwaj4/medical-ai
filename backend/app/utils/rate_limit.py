import threading
import time
from slowapi import Limiter
from starlette.requests import Request
from app.config import settings


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
# In-memory storage: counters are per worker process and reset on restart.
limiter = Limiter(key_func=client_ip)


class FailureThrottle:
    """Tiny per-key failed-attempt counter (e.g. per phone number), used where
    there is no per-account lockout. In-memory, per worker."""

    def __init__(self, max_failures: int, window_seconds: int):
        self.max_failures = max_failures
        self.window = window_seconds
        self._data = {}
        self._lock = threading.Lock()

    def _live(self, key):
        now = time.time()
        return [t for t in self._data.get(key, []) if now - t < self.window]

    def is_blocked(self, key: str) -> bool:
        with self._lock:
            hits = self._live(key)
            self._data[key] = hits
            return len(hits) >= self.max_failures

    def record_failure(self, key: str) -> None:
        with self._lock:
            hits = self._live(key)
            hits.append(time.time())
            self._data[key] = hits

    def reset(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)