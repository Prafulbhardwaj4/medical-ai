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
from app.utils.timezone import ist_today
from app.models.hospital import Hospital
from app.models.doctor import Doctor, UserRole
from app.models.patient import Patient
from app.models.checkin import Checkin
from app.models.consultation import Consultation
from app.models.radiology_order import RadiologyOrder
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
    yield db, state, TestClient(app)
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def _setup(db):
    h = Hospital(name="H", hospital_code="HC1", tier="scale")
    db.add(h); db.flush()
    users = {}
    for role in ("doctor", "receptionist", "pharmacy", "lab", "nurse"):
        d = Doctor(name=role, email=f"{role}@x.in", phone="9", specialization="GP",
                   hashed_password="x", hospital_id=h.id, role=UserRole(role))
        db.add(d); users[role] = d
    p = Patient(url_token="pt1", name="P", phone="9", age=30, gender="M", hospital_id=h.id)
    db.add(p); db.flush()
    ci = Checkin(hospital_id=h.id, patient_id=p.id, token_number="T-1", issue_category="fever",
                 doctor_id=users["doctor"].id, visit_date=ist_today())
    c = Consultation(token_number="T-1", patient_id=p.id, doctor_id=users["doctor"].id)
    db.add_all([ci, c]); db.flush()
    o = RadiologyOrder(patient_id=p.id, hospital_id=h.id, consultation_id=c.id, study_name="Chest", study_type="xray",
                       price=300, status="paid")
    db.add(o); db.commit()
    return users, p, o


def test_only_front_desk_can_revert_and_it_is_audited(env):
    db, state, client = env
    users, p, o = _setup(db)
    for role in ("pharmacy", "lab", "nurse", "doctor"):
        state["user_id"] = users[role].id
        assert client.post(f"/patients/{p.id}/revert-radiology-payment", json={}).status_code == 403
    db.expire_all()
    assert db.query(RadiologyOrder).one().status == "paid"
    state["user_id"] = users["receptionist"].id
    res = client.post(f"/patients/{p.id}/revert-radiology-payment", json={})
    assert res.status_code == 200 and res.json() == {"reverted": 1}
    db.expire_all()
    assert db.query(RadiologyOrder).one().status == "payment_pending"
    row = db.query(AuditLog).filter(AuditLog.action == "radiology_payment_reverted").one()
    info = json.loads(row.details)
    assert info["orders"][0]["before"] == "paid" and info["orders"][0]["price"] == 300