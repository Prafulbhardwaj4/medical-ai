import time
import pytest

from app.config import settings
from app.models.audit_log import AuditLog
from app.models.totp_enrolment import SuperAdminEnrolmentCode
from app.services import totp_enrolment
from app.utils import totp as totp_util
from app.utils.auth import create_totp_pending_token
from app.utils.rate_limit import FailureThrottle
from app.utils.timezone import now_ist_naive

PW = "Str0ng!Pass#1"


@pytest.fixture(autouse=True)
def _clear_throttles():
    FailureThrottle.reset_all_memory()
    yield
    FailureThrottle.reset_all_memory()


@pytest.fixture
def super_admin(make_user):
    return make_user(None, "super_admin", "sa@platform.test", PW)


def _setup(client, admin, code):
    return client.post("/auth/totp/setup", json={"totp_token": create_totp_pending_token(admin.id), "enrolment_code": code})


def _confirm(client, admin, secret):
    code = totp_util._hotp(secret, int(time.time() // totp_util._STEP_SECONDS))
    return client.post("/auth/totp/confirm", json={"totp_token": create_totp_pending_token(admin.id), "code": code})


def test_setup_without_or_with_wrong_code_is_refused_and_audited(client, db, super_admin):
    assert _setup(client, super_admin, "").status_code == 400
    totp_enrolment.issue_enrolment_code(db, super_admin)
    assert _setup(client, super_admin, "AAAA-BBBB-CCCC-DDDD").status_code == 400
    failed = db.query(AuditLog).filter(AuditLog.action == "totp_enrolment_failed", AuditLog.target_id == super_admin.id).count()
    assert failed == 2


def test_right_code_works_once_and_is_stored_only_as_a_hash(client, db, super_admin):
    code = totp_enrolment.issue_enrolment_code(db, super_admin)
    row = db.query(SuperAdminEnrolmentCode).filter_by(doctor_id=super_admin.id).first()
    assert code not in row.code_hash and row.code_hash == totp_enrolment.hash_code(code)
    r = _setup(client, super_admin, code)
    assert r.status_code == 200 and r.json()["secret"]
    assert _confirm(client, super_admin, r.json()["secret"]).status_code == 200
    db.refresh(super_admin)
    assert super_admin.totp_enabled is True
    # spent: cannot be used to enrol again
    super_admin.totp_enabled = False
    db.commit()
    assert _setup(client, super_admin, code).status_code == 400


def test_code_for_another_account_or_expired_code_is_refused(client, db, make_user, super_admin):
    other = make_user(None, "super_admin", "other@platform.test", PW)
    other_code = totp_enrolment.issue_enrolment_code(db, other)
    assert _setup(client, super_admin, other_code).status_code == 400
    mine = totp_enrolment.issue_enrolment_code(db, super_admin)
    row = db.query(SuperAdminEnrolmentCode).filter_by(doctor_id=super_admin.id).first()
    row.expires_at = now_ist_naive().replace(year=2000)
    db.commit()
    assert _setup(client, super_admin, mine).status_code == 400


def test_new_code_cancels_the_old_one(client, db, super_admin):
    old = totp_enrolment.issue_enrolment_code(db, super_admin)
    new = totp_enrolment.issue_enrolment_code(db, super_admin)
    assert _setup(client, super_admin, old).status_code == 400
    assert _setup(client, super_admin, new).status_code == 200


def test_confirm_without_a_claimed_code_is_refused(client, db, super_admin):
    secret = totp_util.generate_secret()
    super_admin.totp_secret_enc = totp_util.encrypt_secret(secret)  # e.g. a stale secret from before this change
    db.commit()
    assert _confirm(client, super_admin, secret).status_code == 400


def test_enrolment_attempts_are_rate_limited_per_account_and_network(client, db, super_admin):
    totp_enrolment.issue_enrolment_code(db, super_admin)
    for _ in range(5):
        _setup(client, super_admin, "WRONG-WRONG-WRONG-WRONG")
    assert _setup(client, super_admin, "WRONG-WRONG-WRONG-WRONG").status_code == 429


def test_create_superadmin_is_disabled_without_a_key(client, monkeypatch):
    monkeypatch.setattr(settings, "SUPER_ADMIN_KEY", "")
    body = {"name": "New Admin", "email": "new@platform.test", "phone": "9876543210", "password": "Zq7#mVLp88xT"}
    assert client.post("/admin/create-superadmin", json=body, headers={"X-Super-Admin-Key": ""}).status_code == 404


def test_create_superadmin_wrong_key_audited_right_key_forces_enrolment(client, db, monkeypatch):
    monkeypatch.setattr(settings, "SUPER_ADMIN_KEY", "k" * 40)
    body = {"name": "New Admin", "email": "new@platform.test", "phone": "9876543210", "password": "Zq7#mVLp88xT"}
    assert client.post("/admin/create-superadmin", json=body, headers={"X-Super-Admin-Key": "wrong"}).status_code == 403
    ok = client.post("/admin/create-superadmin", json=body, headers={"X-Super-Admin-Key": "k" * 40})
    assert ok.status_code == 201 and "issue_totp_enrolment_code" in ok.json()["next_step"]
    actions = {a.action for a in db.query(AuditLog)}
    assert {"create_superadmin_failed", "create_superadmin"} <= actions
    # the new account has no 2FA and cannot enrol without a code
    from app.models.doctor import Doctor
    created = db.query(Doctor).filter(Doctor.email == "new@platform.test").first()
    assert not created.totp_enabled
    assert _setup(client, created, "").status_code == 400


def test_create_superadmin_rejects_a_weak_password(client, monkeypatch):
    monkeypatch.setattr(settings, "SUPER_ADMIN_KEY", "k" * 40)
    body = {"name": "New Admin", "email": "weak@platform.test", "phone": "9876543210", "password": "Password1234"}
    assert client.post("/admin/create-superadmin", json=body, headers={"X-Super-Admin-Key": "k" * 40}).status_code == 400