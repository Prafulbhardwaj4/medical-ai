import logging
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.utils.log_redact import redact_path, AccessLogRedactionFilter
from app.utils.http_safety import SecurityHeadersMiddleware, BodyLimitMiddleware, DefaultRateLimitMiddleware


def test_redact_path_hides_tokens_and_query():
    assert redact_path("/patients/resolve/abc123DEF456ghi789") == "/patients/resolve/[redacted]"
    assert redact_path("/consultations/verify/T-0113-05?hash=deadbeef") == "/consultations/verify/[redacted]"
    assert redact_path("/consultations/ws/transcribe/12?ticket=eyJhbGciOi") == "/consultations/ws/transcribe/12"
    assert redact_path("/admissions/Xk3f9QpLw82mNd7RtYb41ZaH/progress-notes") == "/admissions/[redacted]/progress-notes"


def test_redact_path_keeps_plain_routes_and_ids():
    assert redact_path("/patients/42/test-orders") == "/patients/42/test-orders"
    assert redact_path("/billing/revenue-history/daily/export") == "/billing/revenue-history/daily/export"
    assert redact_path("/admissions/ward-types/1/beds") == "/admissions/ward-types/1/beds"


def test_access_log_filter_rewrites_target():
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "x", 1, '%s - "%s %s HTTP/%s" %d',
                            ("1.2.3.4:5", "GET", "/consultations/ws/transcribe/3?ticket=SECRET", "1.1", 101), None)
    AccessLogRedactionFilter().filter(rec)
    assert "SECRET" not in rec.getMessage() and "ticket" not in rec.getMessage()


def _app(**kw):
    app = FastAPI()
    if "rate" in kw:
        app.add_middleware(DefaultRateLimitMiddleware, limit=kw["rate"], storage_uri="memory://")
    if "max_bytes" in kw:
        app.add_middleware(BodyLimitMiddleware, max_bytes=kw["max_bytes"])
    app.add_middleware(SecurityHeadersMiddleware, hsts=kw.get("hsts", False))

    @app.get("/ping")
    def ping():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/echo")
    async def echo(request: Request):
        return {"n": len(await request.body())}

    return TestClient(app)


def test_security_headers_present_and_hsts_only_in_production():
    r = _app().get("/ping")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-frame-options"] == "DENY"
    assert "microphone=()" in r.headers["permissions-policy"]
    assert "strict-transport-security" not in r.headers
    assert "max-age=" in _app(hsts=True).get("/ping").headers["strict-transport-security"]


def test_body_limit_content_length_and_streaming():
    c = _app(max_bytes=100)
    assert c.post("/echo", content=b"x" * 100).json() == {"n": 100}
    big = c.post("/echo", content=b"x" * 101)
    assert big.status_code == 413 and "too large" in big.json()["detail"]
    assert "x-content-type-options" in big.headers

    def chunks():
        for _ in range(5):
            yield b"y" * 40
    streamed = c.post("/echo", content=chunks())
    assert streamed.status_code == 413


def test_default_rate_limit_only_counts_logged_in_requests_per_token():
    c = _app(rate="3/minute")
    a = {"Authorization": "Bearer token-a"}
    b = {"Authorization": "Bearer token-b"}
    assert [c.get("/ping", headers=a).status_code for _ in range(3)] == [200, 200, 200]
    limited = c.get("/ping", headers=a)
    assert limited.status_code == 429 and "retry-after" in limited.headers
    assert c.get("/ping", headers=b).status_code == 200
    assert all(c.get("/ping").status_code == 200 for _ in range(6))
    assert all(c.get("/health", headers=a).status_code == 200 for _ in range(6))


def test_default_rate_limit_can_be_switched_off():
    c = _app(rate="")
    h = {"Authorization": "Bearer t"}
    assert all(c.get("/ping", headers=h).status_code == 200 for _ in range(10))


def test_real_app_sends_security_headers_and_cors_still_works():
    import app.main
    r = TestClient(app.main.app).get("/", headers={"Origin": "https://medical-s-ai.vercel.app"})
    assert r.status_code == 200
    assert r.headers["x-frame-options"] == "DENY" and r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["access-control-allow-origin"] == "https://medical-s-ai.vercel.app"


def test_cors_regex_startup_warning(caplog):
    from types import SimpleNamespace
    from app import config
    base = {k: getattr(config.settings, k) for k in dir(config.settings) if k.isupper()}
    wide = SimpleNamespace(**{**base, "CORS_ORIGIN_REGEX": r"https://.*\.vercel\.app"})
    with caplog.at_level(logging.WARNING, logger="medscribe"):
        config.log_startup_warnings(wide)
    text = caplog.text
    assert "CORS_ORIGIN_REGEX is set to" in text and "outside your Vercel team" in text
    caplog.clear()
    tight = SimpleNamespace(**{**base, "CORS_ORIGIN_REGEX": r"https://medical-s-ai-[a-z0-9-]+-myteam\.vercel\.app"})
    with caplog.at_level(logging.WARNING, logger="medscribe"):
        config.log_startup_warnings(tight)
    assert "CORS_ORIGIN_REGEX is set to" in caplog.text and "outside your Vercel team" not in caplog.text