import pytest

from app.config import settings
from app.models.audit_log import AuditLog
from app.utils.rate_limit import FailureThrottle

GOOD = "Str0ng!Pass#1"
ATTACKER = {"X-Forwarded-For": "6.6.6.6"}
REAL_USER = {"X-Forwarded-For": "7.7.7.7"}


@pytest.fixture(autouse=True)
def _clear_throttles(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 1)  # these tests send X-Forwarded-For; do not depend on the local .env
    FailureThrottle.reset_all_memory()
    yield
    FailureThrottle.reset_all_memory()


def test_captcha_svg_has_no_readable_text_and_same_api_shape(client):
    from app.utils.auth import generate_captcha_svg, generate_captcha_code, CAPTCHA_ALPHABET
    from app.utils.captcha_font import _FONT
    assert set(CAPTCHA_ALPHABET) <= set(_FONT)
    for _ in range(20):
        code = generate_captcha_code()
        svg = generate_captcha_svg(code)
        assert svg.startswith("<svg") and "<text" not in svg
        assert not any(f">{ch}<" in svg for ch in code)
    body = client.get("/auth/captcha").json()
    assert set(body) >= {"svg", "token"} and "<text" not in body["svg"]


def _login(client, email, password, captcha, headers):
    return client.post("/auth/login", json={"email": email, "password": password, **captcha}, headers=headers)


def test_attacker_cannot_lock_the_real_user_out(client, db, captcha, make_hospital, make_user):
    hospital = make_hospital("H1")
    make_user(hospital, "admin", "real@h1.test", GOOD)
    for _ in range(5):
        r = _login(client, "real@h1.test", "wrong-Password1", captcha, ATTACKER)
    assert r.status_code == 429
    # the attacker's network is now locked out of this account, even with the right password
    assert _login(client, "real@h1.test", GOOD, captcha, ATTACKER).status_code == 429
    # the real user on another network signs in normally
    ok = _login(client, "real@h1.test", GOOD, captcha, REAL_USER)
    assert ok.status_code == 200 and ok.json()["status"] == "success"


def test_one_network_guessing_many_accounts_is_stopped(client, captcha):
    for i in range(20):
        _login(client, f"nobody{i}@x.test", "wrong-Password1", captcha, ATTACKER)
    assert _login(client, "nobody99@x.test", "wrong-Password1", captcha, ATTACKER).status_code == 429


def test_login_events_are_audited_without_secrets(client, db, captcha, make_hospital, make_user):
    hospital = make_hospital("H2")
    make_user(hospital, "admin", "aud@h2.test", GOOD)
    _login(client, "aud@h2.test", "wrong-Password1", captcha, REAL_USER)
    ok = _login(client, "aud@h2.test", GOOD, captcha, REAL_USER)
    token = ok.json()["access_token"]
    client.post("/auth/logout", headers={"Authorization": f"Bearer {token}", **REAL_USER})
    actions = {a.action for a in db.query(AuditLog).filter(AuditLog.hospital_id == hospital.id)}
    assert {"login_failed", "login_success", "logout"} <= actions
    for row in db.query(AuditLog).filter(AuditLog.hospital_id == hospital.id):
        assert "wrong-Password1" not in (row.details or "") and token not in (row.details or "")
        assert GOOD not in (row.details or "")