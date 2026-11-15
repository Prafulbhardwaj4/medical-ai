import calendar
import json
import time
from datetime import datetime, timedelta

from app.config import settings
from app.models.audit_log import AuditLog
from app.utils import totp as totp_util
from app.utils.auth import create_access_token
from app.utils.jwt_compat import jwt
from app.utils.portal_auth import create_portal_access_token

PORTAL_PW = "Str0ng!Pass#1"


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_new_portal_token_is_short_and_carries_session_start(make_portal_account):
    account = make_portal_account("9876500001", PORTAL_PW)
    token = create_portal_access_token(account.id)
    claims = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert claims["auth_at"] <= int(time.time())
    assert claims["exp"] - claims["iat"] <= settings.PORTAL_ACCESS_TOKEN_EXPIRE_MINUTES * 60


def test_refresh_gives_fresh_token_but_never_passes_the_hard_cap(client, make_portal_account, monkeypatch):
    account = make_portal_account("9876500002", PORTAL_PW)
    monkeypatch.setattr(settings, "PORTAL_SESSION_MAX_MINUTES", 60)
    started = datetime.utcnow() - timedelta(minutes=50)
    token = create_portal_access_token(account.id, auth_at=started)
    r = client.post("/portal/auth/refresh", headers=_bearer(token))
    assert r.status_code == 200
    claims = jwt.decode(r.json()["access_token"], settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    # `started` is a naive UTC time, so convert it as UTC (never with .timestamp(), which assumes the computer's own timezone)
    assert claims["exp"] <= calendar.timegm((started + timedelta(minutes=60)).utctimetuple()) + 1  # capped at the original start + 60 min
    assert claims["auth_at"] == calendar.timegm(started.utctimetuple())


def test_old_long_lived_token_keeps_working_but_cannot_be_refreshed_past_the_cap(client, make_portal_account, monkeypatch):
    account = make_portal_account("9876500003", PORTAL_PW)
    monkeypatch.setattr(settings, "PORTAL_SESSION_MAX_MINUTES", 60)
    now = datetime.utcnow()
    old = jwt.encode({"sub": str(account.id), "type": "portal", "iat": now - timedelta(hours=2),
                      "exp": now + timedelta(days=5)}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    assert client.get("/portal/auth/addresses", headers=_bearer(old)).status_code == 200  # issued tokens keep working
    assert client.post("/portal/auth/refresh", headers=_bearer(old)).status_code == 401


def _super_admin_with_2fa(db, make_user):
    admin = make_user(None, "super_admin", "sa@platform.test", "Str0ng!Pass#1")
    secret = totp_util.generate_secret()
    codes, hashes = totp_util.make_backup_codes()
    admin.totp_secret_enc = totp_util.encrypt_secret(secret)
    admin.totp_enabled = True
    admin.totp_backup_codes = json.dumps(hashes)
    admin.totp_last_step = None
    db.commit()
    return admin, secret, codes


def test_backup_codes_regenerate_needs_password_and_current_code(client, db, make_user):
    admin, secret, old_codes = _super_admin_with_2fa(db, make_user)
    headers = _bearer(create_access_token({"sub": str(admin.id), "role": "super_admin"}))
    bad = client.post("/auth/totp/backup-codes/regenerate", json={"password": "wrong-Password1", "code": "000000"}, headers=headers)
    assert bad.status_code == 400
    code = totp_util._hotp(secret, int(time.time() // totp_util._STEP_SECONDS))
    ok = client.post("/auth/totp/backup-codes/regenerate", json={"password": "Str0ng!Pass#1", "code": code}, headers=headers)
    assert ok.status_code == 200 and len(ok.json()["backup_codes"]) == 8
    db.refresh(admin)
    stored = json.loads(admin.totp_backup_codes)
    assert totp_util.consume_backup_code(old_codes[0], stored) is None          # old codes are gone
    assert totp_util.consume_backup_code(ok.json()["backup_codes"][0], stored) is not None
    actions = {a.action for a in db.query(AuditLog).filter(AuditLog.target_id == admin.id)}
    assert {"totp_backup_codes_regen_failed", "totp_backup_codes_regenerated"} <= actions


def test_backup_codes_regenerate_refused_for_non_super_admin(client, make_hospital, make_user):
    hospital = make_hospital("H1")
    doctor = make_user(hospital, "admin", "adm@h1.test", "Str0ng!Pass#1")
    headers = _bearer(create_access_token({"sub": str(doctor.id), "role": "admin"}))
    r = client.post("/auth/totp/backup-codes/regenerate", json={"password": "Str0ng!Pass#1", "code": "123456"}, headers=headers)
    assert r.status_code == 400