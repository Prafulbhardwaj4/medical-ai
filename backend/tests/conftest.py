"""Shared test setup.

The environment is set BEFORE the app is imported, so the tests can never touch a real database:
they always run on a throw-away SQLite file, with migrations, the scheduler and the catalogue autoload off.

Fixtures: client, db, captcha, make_hospital, make_user, make_patient, make_portal_account, two_hospitals, auth_headers.
"""
import itertools
import os
import tempfile

_TMP_DIR = tempfile.mkdtemp(prefix="medscribe-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DIR}/test.db"
os.environ["ENVIRONMENT"] = "test"
os.environ.pop("RENDER", None)
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production-0123456789"
os.environ["RUN_MIGRATIONS_ON_BOOT"] = "false"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["MASTER_CATALOG_AUTOLOAD_ON_BOOT"] = "false"
os.environ["SUPER_ADMIN_KEY"] = ""
os.environ["REDIS_URL"] = ""

import email_validator  # noqa: E402

email_validator.TEST_ENVIRONMENT = True  # accept reserved test domains such as @h1.test

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
import app.main  # noqa: E402,F401  (registers every model)
from app.main import app  # noqa: E402
from app.models.doctor import Doctor, UserRole  # noqa: E402
from app.models.hospital import Hospital  # noqa: E402
from app.models.patient import Patient  # noqa: E402
from app.models.portal import PatientAccount  # noqa: E402
from app.utils.auth import create_access_token, hash_password  # noqa: E402

DEFAULT_PASSWORD = "Str0ng!Pass#1"
TEST_CAPTCHA_ANSWER = "TESTCAPTCHA"
ALL_ROLES = [r.value for r in UserRole]
HOSPITAL_ROLES = [r for r in ALL_ROLES if r != "super_admin"]

_counter = itertools.count(1)
_HASHES = {}


def _hash(password):
    # bcrypt is deliberately slow; hash each distinct test password only once.
    if password not in _HASHES:
        _HASHES[password] = hash_password(password)
    return _HASHES[password]


@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


def _wipe_all_tables():
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture(autouse=True)
def _clean_state():
    from app.utils.rate_limit import limiter
    from app.utils.route_limits import reset_route_limits
    try:
        limiter.reset()
    except Exception:
        pass
    reset_route_limits()
    yield
    _wipe_all_tables()


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def captcha(monkeypatch):
    """Captcha fields that the login endpoints accept (dev answer; never active in production)."""
    monkeypatch.setattr(settings, "DEV_CAPTCHA_ANSWER", TEST_CAPTCHA_ANSWER)
    return {"captcha_token": "test", "captcha_answer": TEST_CAPTCHA_ANSWER}


@pytest.fixture()
def make_hospital(db):
    def _make(name="Test Hospital", **kwargs):
        n = next(_counter)
        kwargs.setdefault("hospital_code", f"TH{n:04d}")
        hospital = Hospital(name=name, **kwargs)
        db.add(hospital)
        db.commit()
        db.refresh(hospital)
        return hospital
    return _make


@pytest.fixture()
def make_user(db):
    def _make(hospital, role="doctor", email=None, password=DEFAULT_PASSWORD, **kwargs):
        n = next(_counter)
        user = Doctor(
            name=kwargs.pop("name", f"User {n}"),
            email=(email or f"user{n}@test.example").lower(),
            phone=kwargs.pop("phone", f"90000{n:05d}"),
            specialization=kwargs.pop("specialization", "General"),
            hashed_password=_hash(password),
            role=UserRole(role),
            hospital_id=hospital.id if hospital is not None else None,
            **kwargs,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    return _make


@pytest.fixture()
def make_patient(db, make_user):
    def _make(hospital, name="Test Patient", **kwargs):
        n = next(_counter)
        if kwargs.get("created_by") is None:
            kwargs["created_by"] = make_user(hospital, "receptionist").id
        patient = Patient(
            name=name,
            phone=kwargs.pop("phone", f"98000{n:05d}"),
            age=kwargs.pop("age", 35),
            gender=kwargs.pop("gender", "male"),
            patient_uid=kwargs.pop("patient_uid", f"PU{n:06d}"),
            url_token=kwargs.pop("url_token", f"tok{n:010d}"),
            hospital_id=hospital.id,
            **kwargs,
        )
        db.add(patient)
        db.commit()
        db.refresh(patient)
        return patient
    return _make


@pytest.fixture()
def make_portal_account(db):
    def _make(phone="9876500000", password=DEFAULT_PASSWORD, **kwargs):
        from app.utils.portal_auth import hash_password as portal_hash
        account = PatientAccount(phone=phone, password_hash=portal_hash(password), **kwargs)
        db.add(account)
        db.commit()
        db.refresh(account)
        return account
    return _make


@pytest.fixture()
def two_hospitals(make_hospital, make_user):
    """Two hospitals, each with one user of every hospital role.
    Returns {"h1": Hospital, "h2": Hospital, "users": {"h1": {role: Doctor}, "h2": {role: Doctor}}}."""
    h1, h2 = make_hospital("Hospital One"), make_hospital("Hospital Two")
    users = {
        key: {role: make_user(h, role, f"{role}.{key}@test.example") for role in HOSPITAL_ROLES}
        for key, h in (("h1", h1), ("h2", h2))
    }
    return {"h1": h1, "h2": h2, "users": users}


@pytest.fixture()
def auth_headers():
    """auth_headers(user) -> Authorization header carrying a valid staff access token for that user."""
    def _headers(user):
        return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}
    return _headers