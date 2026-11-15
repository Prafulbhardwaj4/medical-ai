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
from app.models.hospital import Hospital
from app.models.doctor import Doctor, UserRole
from app.models.patient import Patient
from app.models.consultation import Consultation
from app.models.admission import Admission, AdmissionMedicationOrder
from app.models.admission_vitals import AdmissionVitals
from app.models.admission_referral import AdmissionReferral
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


def _hospital(db, n):
    h = Hospital(name=f"H{n}", hospital_code=f"HC{n}", tier="scale")
    db.add(h); db.flush()
    users = {}
    for role in ("doctor", "nurse", "receptionist", "pharmacy", "lab", "admin"):
        d = Doctor(name=f"{role}{n}", email=f"{role}{n}@x.in", phone="9", specialization="GP",
                   hashed_password="x", hospital_id=h.id, role=UserRole(role))
        db.add(d); users[role] = d
    p = Patient(url_token=f"pt{n}", name=f"P{n}", phone="9", age=30, gender="M", hospital_id=h.id)
    db.add(p); db.flush()
    doc = users["doctor"]
    a = Admission(public_token=f"adm{n}", patient_id=p.id, hospital_id=h.id, admitting_doctor_id=doc.id,
                  ward="W", bed_number="1", diagnosis="old dx")
    db.add(a); db.flush()
    v = AdmissionVitals(admission_id=a.id, recorded_by=doc.id, data="{}")
    c = Consultation(token_number=f"tok{n}", patient_id=p.id, doctor_id=doc.id, diagnosis=f"secret dx {n}")
    r = AdmissionReferral(patient_id=p.id, hospital_id=h.id, referred_by=doc.id, status="pending")
    db.add_all([v, c, r]); db.commit()
    return dict(h=h, users=users, p=p, a=a, v=v, c=c, r=r)


def test_last_diagnosis_does_not_leak_other_hospital(env):
    db, state, client = env
    h1, h2 = _hospital(db, 1), _hospital(db, 2)
    state["user_id"] = h2["users"]["doctor"].id
    res = client.get(f"/admissions/last-diagnosis/{h1['p'].id}")
    assert res.status_code == 200 and res.json() == {"diagnosis": None}
    state["user_id"] = h1["users"]["doctor"].id
    assert client.get(f"/admissions/last-diagnosis/{h1['p'].id}").json() == {"diagnosis": "secret dx 1"}


def test_vitals_token_same_404_for_missing_and_other_hospital(env):
    db, state, client = env
    h1, h2 = _hospital(db, 1), _hospital(db, 2)
    state["user_id"] = h2["users"]["doctor"].id
    other = client.get(f"/admissions/vitals-token-for/{h1['v'].id}")
    missing = client.get("/admissions/vitals-token-for/999999")
    assert other.status_code == missing.status_code == 404
    assert other.json() == missing.json()
    state["user_id"] = h1["users"]["doctor"].id
    assert client.get(f"/admissions/vitals-token-for/{h1['v'].id}").json() == {"token": "adm1"}


def test_diagnosis_role_gate_and_audit(env):
    db, state, client = env
    h1 = _hospital(db, 1)
    for role in ("pharmacy", "lab"):
        state["user_id"] = h1["users"][role].id
        assert client.patch("/admissions/adm1/diagnosis", json={"diagnosis": "x"}).status_code == 403
    assert db.query(AuditLog).filter(AuditLog.action == "admission_diagnosis_updated").count() == 0
    state["user_id"] = h1["users"]["doctor"].id
    res = client.patch("/admissions/adm1/diagnosis", json={"diagnosis": "new dx"})
    assert res.status_code == 200
    db.expire_all()
    row = db.query(AuditLog).filter(AuditLog.action == "admission_diagnosis_updated").one()
    assert json.loads(row.details) == {"before": "old dx", "after": "new dx"}
    assert row.hospital_id == h1["h"].id


def test_diagnosis_other_hospital_is_404(env):
    db, state, client = env
    h1, h2 = _hospital(db, 1), _hospital(db, 2)
    state["user_id"] = h2["users"]["doctor"].id
    assert client.patch("/admissions/adm1/diagnosis", json={"diagnosis": "x"}).status_code == 404


def test_cancel_referral_role_gate_and_audit(env):
    db, state, client = env
    h1 = _hospital(db, 1)
    state["user_id"] = h1["users"]["pharmacy"].id
    assert client.delete(f"/admissions/referrals/{h1['r'].id}").status_code == 403
    state["user_id"] = h1["users"]["receptionist"].id
    assert client.delete(f"/admissions/referrals/{h1['r'].id}").status_code == 200
    db.expire_all()
    row = db.query(AuditLog).filter(AuditLog.action == "admission_referral_cancelled").one()
    assert json.loads(row.details)["before"] == "pending"