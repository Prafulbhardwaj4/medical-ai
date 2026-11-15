"""Error tracking and alert counters (optional Sentry, no patient data in events).

- init_sentry(): only when SENTRY_DSN is set and sentry-sdk is installed.
- record_audit_write_failure(): fixed marker AUDIT_WRITE_FAILED + counter + Sentry.
- record_login_failure(): counts failed logins and lockouts in a fixed window and alerts once per
  window when LOGIN_FAILURE_ALERT_THRESHOLD is crossed (shared across workers when REDIS_URL is set).
- snapshot(): the counters, exposed on /health for the uptime monitor.
"""
import logging
import os
import threading
import time

from app.config import settings

log = logging.getLogger("medscribe.monitoring")

_lock = threading.Lock()
_counters = {"audit_write_failures": 0, "server_errors": 0, "login_failures": 0, "lockouts": 0}
_buckets = {}
_sentry_ready = False

_KEEP_MESSAGE_PREFIXES = ("AUDIT_WRITE_FAILED", "LOGIN_FAILURE_SPIKE")
_DROP_HEADERS = {"authorization", "cookie", "set-cookie", "x-forwarded-for", "x-real-ip"}


def scrub_event(event, hint):
    """Sentry before_send: removes request bodies, query strings, tokens, local variables,
    breadcrumbs and exception text (which can carry SQL parameters or patient words)."""
    try:
        req = event.get("request")
        if isinstance(req, dict):
            for key in ("data", "cookies", "query_string"):
                req.pop(key, None)
            headers = req.get("headers")
            if isinstance(headers, dict):
                req["headers"] = {k: v for k, v in headers.items() if str(k).lower() not in _DROP_HEADERS}
            url = req.get("url")
            if isinstance(url, str):
                req["url"] = url.split("?", 1)[0]
        event.pop("user", None)
        event.pop("extra", None)
        event["breadcrumbs"] = {"values": []}
        for exc in (event.get("exception") or {}).get("values") or []:
            exc["value"] = "[removed]"
            for frame in (exc.get("stacktrace") or {}).get("frames") or []:
                frame.pop("vars", None)
        entry = event.get("logentry")
        if isinstance(entry, dict):
            message = str(entry.get("message") or entry.get("formatted") or "")
            if not message.startswith(_KEEP_MESSAGE_PREFIXES):
                entry["message"] = "[removed]"
                entry.pop("formatted", None)
            entry.pop("params", None)
    except Exception:
        return None
    return event


def init_sentry() -> bool:
    global _sentry_ready
    dsn = (settings.SENTRY_DSN or "").strip()
    if not dsn:
        log.info("SENTRY_DSN is not set: error tracking is off.")
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        log.warning("SENTRY_DSN is set but sentry-sdk is not installed: error tracking is off.")
        return False
    try:
        sentry_sdk.init(
            dsn=dsn,
            send_default_pii=False,
            before_send=scrub_event,
            traces_sample_rate=0.0,
            max_breadcrumbs=0,
            environment=os.getenv("ENVIRONMENT") or ("production" if os.getenv("RENDER") else "development"),
            integrations=[LoggingIntegration(level=None, event_level=None)],
        )
    except Exception as e:
        log.error("Sentry could not start (%s): error tracking is off.", type(e).__name__)
        return False
    _sentry_ready = True
    log.info("Sentry error tracking is on (patient data scrubbed).")
    return True


def capture_exception(exc) -> None:
    if not _sentry_ready:
        return
    try:
        import sentry_sdk
        sentry_sdk.capture_exception(exc)
    except Exception:
        pass


def capture_message(message: str, level: str = "error") -> None:
    if not _sentry_ready:
        return
    try:
        import sentry_sdk
        sentry_sdk.capture_message(message, level=level)
    except Exception:
        pass


def record_server_error(exc=None) -> None:
    with _lock:
        _counters["server_errors"] += 1
    if exc is not None:
        capture_exception(exc)


def record_audit_write_failure(exc=None) -> None:
    with _lock:
        _counters["audit_write_failures"] += 1
    logging.getLogger("audit").error("AUDIT_WRITE_FAILED an audit entry could not be saved; see the line above for the action")
    if exc is not None:
        capture_exception(exc)
    else:
        capture_message("AUDIT_WRITE_FAILED", "error")


def _bucket_count(window: int) -> int:
    """Failures counted so far in the current fixed window (Redis when available, else this process)."""
    bucket = int(time.time() // window)
    try:
        from app.utils.rate_limit import _redis
        r = _redis()
        if r is not None:
            key = f"medscribe:lf:{bucket}"
            n = int(r.incr(key))
            if n == 1:
                r.expire(key, window * 2)
            return n
    except Exception:
        pass
    with _lock:
        for old in [b for b in _buckets if b < bucket]:
            _buckets.pop(old, None)
        _buckets[bucket] = _buckets.get(bucket, 0) + 1
        return _buckets[bucket]


def record_login_failure(locked: bool = False) -> None:
    """Call once per failed login (staff or portal). Never pass an email, name or password."""
    with _lock:
        _counters["login_failures"] += 1
        if locked:
            _counters["lockouts"] += 1
    window = max(int(settings.LOGIN_FAILURE_ALERT_WINDOW_SECONDS), 1)
    threshold = max(int(settings.LOGIN_FAILURE_ALERT_THRESHOLD), 1)
    if _bucket_count(window) == threshold:
        log.error("LOGIN_FAILURE_SPIKE %d failed logins within %d seconds", threshold, window)
        capture_message(f"LOGIN_FAILURE_SPIKE {threshold} failed logins within {window} seconds", "error")


def record_lockout() -> None:
    """Call when an account or network gets locked out (the failed attempt itself is counted by record_login_failure)."""
    with _lock:
        _counters["lockouts"] += 1


def snapshot() -> dict:
    with _lock:
        return dict(_counters)


def reset_for_tests() -> None:
    with _lock:
        for k in _counters:
            _counters[k] = 0
        _buckets.clear()