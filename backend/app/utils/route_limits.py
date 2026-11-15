"""Per-IP limit that is added to a route as a normal FastAPI dependency (so the route function itself, and any code
or test that calls it directly, stays unchanged). Uses Redis when REDIS_URL is set, otherwise memory. If the counter
store fails the request goes through."""
from fastapi import HTTPException, Request

from app.config import settings
from app.utils.rate_limit import client_ip

_state = {}


def _strategy():
    if "strategy" not in _state:
        from limits.storage import storage_from_string
        from limits.strategies import FixedWindowRateLimiter
        try:
            storage = storage_from_string(settings.REDIS_URL or "memory://")
        except Exception:
            storage = storage_from_string("memory://")
        _state["storage"] = storage
        _state["strategy"] = FixedWindowRateLimiter(storage)
    return _state["strategy"]


def reset_route_limits() -> None:
    """Clears every counter (tests only)."""
    storage = _state.get("storage")
    if storage is not None:
        try:
            storage.reset()
        except Exception:
            pass


def per_ip_limit(scope: str, *limits: str):
    from limits import parse
    items = [parse(text) for text in limits]

    def _dependency(request: Request):
        try:
            strategy = _strategy()
            ip = client_ip(request)
            for item in items:
                if not strategy.hit(item, scope, ip):
                    raise HTTPException(
                        status_code=429,
                        detail="You are doing that too quickly. Please wait a moment and try again.",
                        headers={"Retry-After": str(item.get_expiry())},
                    )
        except HTTPException:
            raise
        except Exception:
            return None
        return None

    return _dependency