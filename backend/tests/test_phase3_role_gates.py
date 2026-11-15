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

ALL_ROLES = [r.value for r in UserRole]

# (roles allowed, [(method, path), ...]). Every other role must get 403; an allowed role must NOT get 403.
GATES = [
    (('doctor', 'nurse', 'receptionist', 'assistant', 'admin', 'sub_admin'), [
        ('GET', '/admissions/last-diagnosis/1'),
        ('POST', '/admissions'),
        ('GET', '/admissions/referrals'),
        ('GET', '/admissions/ward-types/1/beds'),
        ('GET', '/admissions/ward-types'),
        ('GET', '/admissions/active'),
        ('GET', '/admissions/history'),
        ('GET', '/admissions/1'),
        ('GET', '/admissions/1/consents'),
        ('GET', '/admissions/1/deposit-summary'),
        ('GET', '/admissions/1/discharge-preview'),
        ('GET', '/admissions/1/invoice/pdf'),
        ('GET', '/admissions/1/progress-notes'),
        ('GET', '/referrals/1'),
        ('GET', '/referrals/records/for-admission/1'),
    ]),
    (('doctor',), [
        ('GET', '/consultations/today'),
        ('GET', '/consultations/active-draft'),
        ('POST', '/consultations/draft/1'),
        ('GET', '/consultations/ai-scribe-status'),
        ('POST', '/consultations/structure/1'),
        ('POST', '/consultations/confirm/1'),
        ('PATCH', '/consultations/update/1'),
        ('POST', '/consultations/void/1'),
    ]),
    (('doctor', 'receptionist', 'admin', 'sub_admin'), [
        ('GET', '/consultations/patient-feedback/1'),
    ]),
    (('lab', 'admin', 'sub_admin'), [
        ('GET', '/lab/orders/1/tat-trace'),
    ]),
    (('doctor', 'nurse', 'receptionist', 'assistant', 'admin', 'sub_admin', 'radiology'), [
        ('GET', '/radiology/orders/1/pdf'),
    ]),
    (('doctor', 'nurse', 'assistant', 'admin', 'sub_admin'), [
        ('GET', '/pharmacy/medicine-orders/schedule-x-status/1'),
    ]),
    (('receptionist', 'admin', 'sub_admin', 'doctor', 'nurse', 'assistant', 'pharmacy'), [
        ('GET', '/patients/lookup'),
        ('GET', '/patients/'),
        ('GET', '/patients/checkin-by-token/1'),
        ('GET', '/patients/1/documents'),
    ]),
    (('receptionist', 'admin', 'sub_admin'), [
        ('GET', '/patients/doctor-coverage-status/1'),
        ('GET', '/patients/1/preferred-doctor'),
        ('GET', '/patients/checkins/1/slip'),
        ('GET', '/patients/1/pending-tasks'),
        ('POST', '/patients/1/collect-radiology-payment-anyday'),
        ('GET', '/patients/1/pending-test-fees'),
        ('GET', '/patients/1/pending-radiology-fees'),
        ('PATCH', '/patients/radiology-orders/1/toggle-include'),
        ('POST', '/patients/1/collect-radiology-payment'),
    ]),
    (('receptionist', 'admin', 'sub_admin', 'doctor', 'nurse', 'assistant'), [
        ('GET', '/patients/resolve/1'),
        ('GET', '/patients/1/checkin-today'),
        ('GET', '/patients/1'),
        ('GET', '/patients/queue/today'),
        ('GET', '/patients/1/pending-opd-charges'),
        ('GET', '/patients/1/test-orders'),
        ('GET', '/patients/1/allergies'),
    ]),
]


@pytest.fixture(scope="module")
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
    h = Hospital(name="H", hospital_code="HC1", tier="scale")
    db.add(h); db.flush()
    users = {}
    for role in ALL_ROLES:
        d = Doctor(name=role, email=f"{role}@x.in", phone="9", specialization="GP",
                   hashed_password="x", hospital_id=h.id if role != "super_admin" else None, role=UserRole(role))
        db.add(d); users[role] = d
    db.commit()
    ids = {r: u.id for r, u in users.items()}
    yield state, ids, TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def _cases():
    for allowed, routes in GATES:
        for method, path in routes:
            yield pytest.param(allowed, method, path, id=f"{method} {path}")


@pytest.mark.parametrize("allowed,method,path", list(_cases()))
def test_role_gate(env, allowed, method, path):
    state, ids, client = env
    for role in ALL_ROLES:
        state["user_id"] = ids[role]
        res = client.request(method, path, json={} if method != "GET" else None)
        if role in allowed:
            assert res.status_code != 403, f"{role} should be allowed on {method} {path}"
        else:
            assert res.status_code == 403, f"{role} should be refused on {method} {path}, got {res.status_code}"