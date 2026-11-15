from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main  # noqa: F401  (importing the app registers every model)
from app.database import Base
from app.models.blacklisted_token import BlacklistedToken
from app.models.doctor import Doctor, UserRole
from app.models.hospital import Hospital
from app.utils.auth import blacklist_token, create_access_token, get_current_doctor, hash_token
from app.utils.timezone import now_ist_naive


@pytest.fixture()
def p9db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.engine_ref = engine
    yield session
    session.close()
    engine.dispose()


def _hospital(db, code="H1"):
    h = Hospital(name="Test Hospital", hospital_code=code)
    db.add(h)
    db.commit()
    return h


def _doctor(db, hospital_id, email="d@example.com", role=UserRole.doctor):
    d = Doctor(name="Dr Test", email=email, phone="9000000000", specialization="GP",
               hashed_password="x", role=role, hospital_id=hospital_id)
    db.add(d)
    db.commit()
    return d


def _creds(doctor):
    token = create_access_token({"sub": str(doctor.id)})
    return token, HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _selects(db, fn):
    seen = []

    def count(conn, cursor, statement, *a):
        if statement.lstrip().upper().startswith("SELECT"):
            seen.append(statement)

    event.listen(db.engine_ref, "before_cursor_execute", count)
    try:
        result = fn()
    finally:
        event.remove(db.engine_ref, "before_cursor_execute", count)
    return result, seen


def test_valid_token_costs_one_query(p9db):
    h = _hospital(p9db)
    d = _doctor(p9db, h.id)
    _, creds = _creds(d)
    got, selects = _selects(p9db, lambda: get_current_doctor(creds, p9db))
    assert got.id == d.id
    assert len(selects) == 1


def test_super_admin_without_hospital_is_accepted(p9db):
    d = _doctor(p9db, None, email="sa@example.com", role=UserRole.super_admin)
    _, creds = _creds(d)
    assert get_current_doctor(creds, p9db).id == d.id


def test_blacklisted_token_rejected_and_checked_every_time(p9db):
    h = _hospital(p9db)
    d = _doctor(p9db, h.id)
    token, creds = _creds(d)
    assert get_current_doctor(creds, p9db).id == d.id
    blacklist_token(token, p9db)  # logout between two requests
    with pytest.raises(HTTPException) as e:
        get_current_doctor(creds, p9db)
    assert e.value.status_code == 401


def test_legacy_raw_blacklist_row_still_rejected(p9db):
    h = _hospital(p9db)
    d = _doctor(p9db, h.id)
    token, creds = _creds(d)
    p9db.add(BlacklistedToken(token=token, blacklisted_at=now_ist_naive()))
    p9db.commit()
    with pytest.raises(HTTPException):
        get_current_doctor(creds, p9db)


def test_other_tokens_unaffected_by_a_blacklist_row(p9db):
    h = _hospital(p9db)
    d = _doctor(p9db, h.id)
    p9db.add(BlacklistedToken(token_hash=hash_token("some-other-token"), blacklisted_at=now_ist_naive()))
    p9db.commit()
    _, creds = _creds(d)
    assert get_current_doctor(creds, p9db).id == d.id


def test_inactive_user_rejected(p9db):
    h = _hospital(p9db)
    d = _doctor(p9db, h.id)
    _, creds = _creds(d)
    d.is_active = False
    p9db.commit()
    with pytest.raises(HTTPException) as e:
        get_current_doctor(creds, p9db)
    assert e.value.status_code == 401


def test_inactive_hospital_rejected_with_plain_message(p9db):
    h = _hospital(p9db)
    d = _doctor(p9db, h.id)
    _, creds = _creds(d)
    h.is_active = False
    p9db.commit()
    with pytest.raises(HTTPException) as e:
        get_current_doctor(creds, p9db)
    assert e.value.status_code == 401 and "deactivated" in e.value.detail


def test_token_older_than_password_change_rejected(p9db):
    h = _hospital(p9db)
    d = _doctor(p9db, h.id)
    _, creds = _creds(d)
    d.password_changed_at = datetime.utcnow() + timedelta(minutes=5)
    p9db.commit()
    with pytest.raises(HTTPException):
        get_current_doctor(creds, p9db)


def test_unknown_user_rejected(p9db):
    token = create_access_token({"sub": "9999"})
    with pytest.raises(HTTPException):
        get_current_doctor(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), p9db)