"""Plain ASGI middleware for every API response: security headers, a request body limit and a generous
default rate limit for logged-in calls. Written as ASGI (not BaseHTTPMiddleware) so the body limit also
applies to streamed uploads."""
import hashlib
import json
import logging

log = logging.getLogger("medscribe")

_SECURITY_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
)
_HSTS = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")


class SecurityHeadersMiddleware:
    def __init__(self, app, hsts: bool = False):
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def _send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                for k, v in _SECURITY_HEADERS + ((_HSTS,) if self.hsts else ()):
                    if k not in present:
                        headers.append((k, v))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, _send)


class _TooLarge(Exception):
    pass


def _json_response_parts(status: int, detail: str, extra_headers=()):
    body = json.dumps({"detail": detail}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), *extra_headers]
    return (
        {"type": "http.response.start", "status": status, "headers": headers},
        {"type": "http.response.body", "body": body},
    )


class BodyLimitMiddleware:
    """Refuses a request whose Content-Length is over max_bytes, and also counts the bytes of a streamed body."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = int(max_bytes or 0)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.max_bytes <= 0:
            return await self.app(scope, receive, send)
        limit = self.max_bytes
        message = "That request is too large. Please send a smaller file or less data."

        declared = None
        for k, v in scope.get("headers", []):
            if k == b"content-length":
                try:
                    declared = int(v)
                except ValueError:
                    declared = None
                break
        if declared is not None and declared > limit:
            start, body = _json_response_parts(413, message)
            await send(start)
            await send(body)
            return

        state = {"received": 0, "rejected": False, "started": False, "body_sent": False}

        async def _receive():
            msg = await receive()
            if msg["type"] == "http.request":
                state["received"] += len(msg.get("body", b""))
                if state["received"] > limit:
                    state["rejected"] = True
                    raise _TooLarge()
            return msg

        async def _send(msg):
            if state["rejected"]:
                # Whatever the app tried to answer (it may have turned the abort into a 400), the client gets 413.
                if msg["type"] == "http.response.start" and not state["started"]:
                    state["started"] = True
                    start, _ = _json_response_parts(413, message)
                    await send(start)
                elif msg["type"] == "http.response.body" and not state["body_sent"]:
                    state["body_sent"] = True
                    _, body = _json_response_parts(413, message)
                    await send(body)
                return
            if msg["type"] == "http.response.start":
                state["started"] = True
            await send(msg)

        try:
            await self.app(scope, _receive, _send)
        except _TooLarge:
            if not state["started"]:
                start, body = _json_response_parts(413, message)
                await send(start)
                await send(body)


class DefaultRateLimitMiddleware:
    """A generous per-session limit for every logged-in request (a request that carries a Bearer token).
    Public routes keep their own explicit limits. Counting is per session token, so one busy hospital behind a
    single IP address does not share one allowance. Uses Redis when REDIS_URL is set, otherwise memory.
    If the counter store fails, the request goes through (never block care because of the limiter)."""

    EXEMPT = ("/health", "/health/live")

    def __init__(self, app, limit: str, storage_uri: str = "memory://"):
        self.app = app
        self._limit_text = (limit or "").strip()
        self._storage_uri = storage_uri or "memory://"
        self._limiter = None
        self._item = None

    def _ready(self) -> bool:
        if not self._limit_text:
            return False
        if self._limiter is None:
            from limits import parse
            from limits.storage import storage_from_string
            from limits.strategies import FixedWindowRateLimiter
            try:
                storage = storage_from_string(self._storage_uri)
            except Exception:
                storage = storage_from_string("memory://")
            self._limiter = FixedWindowRateLimiter(storage)
            self._item = parse(self._limit_text)
        return True

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") == "OPTIONS" or scope.get("path") in self.EXEMPT:
            return await self.app(scope, receive, send)
        token = None
        for k, v in scope.get("headers", []):
            if k == b"authorization":
                parts = v.decode("latin-1").split(None, 1)
                if len(parts) == 2 and parts[0].lower() == "bearer":
                    token = parts[1].strip()
                break
        if not token or not self._ready():
            return await self.app(scope, receive, send)
        key = "default:" + hashlib.sha256(token.encode()).hexdigest()[:32]
        try:
            allowed = self._limiter.hit(self._item, key)
        except Exception:
            allowed = True
        if not allowed:
            log.warning("RATE_LIMIT default limit reached path=%s", scope.get("path"))
            start, body = _json_response_parts(
                429, "You are sending requests too quickly. Please wait a moment and try again.",
                extra_headers=[(b"retry-after", str(self._item.get_expiry()).encode())],
            )
            await send(start)
            await send(body)
            return
        await self.app(scope, receive, send)