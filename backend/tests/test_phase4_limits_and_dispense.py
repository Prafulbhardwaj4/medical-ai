import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
import app.main
from app.main import app
from app.utils.auth import get_current_doctor
from app.utils.rate_limit import limiter
from app.utils.route_limits import reset_route_limits
from app.utils.qr_hash import hash_equals
from app.models.hospital import Hospital
from app.models.doctor import Doctor, UserRole
from app.models.patient import Patient
from app.models.consultation import Consultation
from app.models.audit_log import AuditLog


@pytest.fixture()
def env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    state = {"user_id": None}

    def _get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    def _current():
        s = Session()
        u = s.query(Doctor).filter(Doctor.id == state["user_id"]).first()
        s.expunge(u)
        s.close()
        return u

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_doctor] = _current
    limiter.reset()
    reset_route_limits()
    h = Hospital(name="H", hospital_code="HC1", tier="scale")
    db.add(h); db.flush()
    doc = Doctor(name="D", email="d@x.in", phone="9", specialization="GP", hashed_password="x",
                 hospital_id=h.id, role=UserRole("doctor"))
    p = Patient(url_token="pt1", name="P", phone="9", age=30, gender="M", hospital_id=h.id)
    db.add_all([doc, p]); db.flush()
    cons = Consultation(token_number="T-1", patient_id=p.id, doctor_id=doc.id, verify_hash="GOODHASH")
    db.add(cons); db.commit()
    state["user_id"] = doc.id
    yield db, state, TestClient(app), doc, cons
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def test_hash_equals():
    assert hash_equals("ABC123", "ABC123")
    assert not hash_equals("ABC123", "ABC124")
    assert not hash_equals(None, "")
    assert not hash_equals("", "")
    assert not hash_equals("ABC", None)


def test_dispense_audits_every_outcome_and_refuses_twice(env):
    db, state, client, doc, cons = env
    bad = client.post("/consultations/verify/T-1/dispense?hash=WRONG")
    assert bad.status_code == 404
    ok = client.post("/consultations/verify/T-1/dispense?hash=GOODHASH")
    assert ok.status_code == 200
    again = client.post("/consultations/verify/T-1/dispense?hash=GOODHASH")
    assert again.status_code == 400
    db.expire_all()
    rows = {(r.action, json.loads(r.details)["result"]) for r in db.query(AuditLog).filter(
        AuditLog.action.in_(["prescription_dispensed", "prescription_dispense_refused"])).all()}
    assert rows == {("prescription_dispense_refused", "invalid_token_or_code"),
                    ("prescription_dispensed", "dispensed"),
                    ("prescription_dispense_refused", "already_dispensed")}
    one = db.query(AuditLog).filter(AuditLog.action == "prescription_dispensed").one()
    assert "ip" in json.loads(one.details) and json.loads(one.details)["token_id"] == cons.id


def test_dispense_limited_per_token(env):
    db, state, client, doc, cons = env
    codes = [client.post("/consultations/verify/T-1/dispense?hash=WRONG").status_code for _ in range(6)]
    assert codes[:5] == [404] * 5 and codes[5] == 429
    assert client.post("/consultations/verify/T-2/dispense?hash=WRONG").status_code == 404


def test_chat_upload_is_limited_per_ip(env):
    db, state, client, doc, cons = env
    codes = []
    for _ in range(31):
        r = client.post("/chat/upload", files={"file": ("a.exe", b"MZ", "application/octet-stream")})
        codes.append(r.status_code)
    assert set(codes[:30]) == {400} and codes[30] == 429


def test_new_explicit_limits_are_registered():
    keys = " ".join(limiter._route_limits.keys())
    assert "complete_registration" in keys and "book_appointment" in keys