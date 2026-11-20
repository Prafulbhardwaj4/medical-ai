import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.utils.auth import get_current_doctor
from app.utils.rate_limit import limiter
from app.utils.route_limits import reset_route_limits
from app.models.hospital import Hospital
from app.models.doctor import Doctor, UserRole
from app.models.patient import Patient
from app.models.audit_log import AuditLog
from app.utils.timezone import now_ist_naive


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
    users = {}
    for i, r in enumerate(["admin", "doctor", "receptionist"]):
        u = Doctor(name=f"U{r}", email=f"{r}@x.in", phone=f"9{i}", specialization="GP",
                   hashed_password="x", hospital_id=h.id, role=UserRole(r))
        db.add(u); users[r] = u
    db.flush()
    p = Patient(url_token="pt1", name="Secret Name", phone="9", age=30, gender="M", hospital_id=h.id,
                patient_uid="MS-0001", created_by=users["admin"].id)
    db.add(p); db.flush()
    db.add(AuditLog(hospital_id=h.id, actor_id=999, actor_name="Real Person", actor_role="super_admin",
                    action="hospital_updated", target_type="hospital", target_id=h.id,
                    target_label="H", details="by real@person.in", created_at=now_ist_naive()))
    db.add(AuditLog(hospital_id=h.id, actor_id=users["doctor"].id, actor_name="Udoctor", actor_role="doctor",
                    action="patient_updated", target_type="patient", target_id=p.id,
                    target_label="x", details="d", created_at=now_ist_naive()))
    db.commit()
    state["user_id"] = users["admin"].id
    yield db, state, TestClient(app), users, p, h
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def test_admin_sees_platform_actions_with_generic_label(env):
    db, state, client, users, p, h = env
    r = client.get("/audit/logs")
    assert r.status_code == 200
    rows = {x["action"]: x for x in r.json()["logs"]}
    plat = rows["hospital_updated"]
    assert plat["actor_name"] == "ScribeKare platform support"
    assert plat["actor_role"] == "platform_support"
    assert plat["details"] is None
    assert "Real Person" not in r.text and "real@person.in" not in r.text
    assert rows["patient_updated"]["actor_name"] == "Udoctor"


def test_platform_label_in_summary_actions_and_export(env):
    db, state, client, users, p, h = env
    s = client.get("/audit/summary").json()
    assert s["total_events"] == 2
    assert any(x["actor_name"] == "ScribeKare platform support" for x in s["recent"])
    assert "hospital_updated" in client.get("/audit/actions").json()
    e = client.get("/audit/export")
    assert "ScribeKare platform support" in e.text
    assert "Real Person" not in e.text and "real@person.in" not in e.text


def test_actor_filter_never_returns_platform_rows(env):
    db, state, client, users, p, h = env
    r = client.get("/audit/logs?actor_id=999")
    assert r.json()["total"] == 0


def test_non_admin_still_forbidden(env):
    db, state, client, users, p, h = env
    state["user_id"] = users["doctor"].id
    assert client.get("/audit/logs").status_code == 403
    assert client.get("/audit/summary").status_code == 403
    assert client.get("/audit/export").status_code == 403


def test_record_access_logged_with_ids_only(env):
    db, state, client, users, p, h = env
    state["user_id"] = users["receptionist"].id
    assert client.get(f"/patients/{p.id}").status_code == 200
    assert client.get(f"/patients/{p.id}/documents").status_code == 200
    assert client.get("/patients/").status_code == 200
    db.expire_all()
    rows = db.query(AuditLog).filter(AuditLog.action.like("%_viewed")).all()
    acts = {r.action: r for r in rows}
    assert {"patient_record_viewed", "patient_documents_viewed", "patient_list_viewed"} <= set(acts)
    assert acts["patient_record_viewed"].target_label == f"Patient {p.id}"
    for r in rows:
        assert "Secret" not in (r.target_label or "") and "Secret" not in (r.details or "")


def test_record_access_dedupes_and_is_tenant_safe(env):
    db, state, client, users, p, h = env
    state["user_id"] = users["receptionist"].id
    for _ in range(3):
        client.get(f"/patients/{p.id}")
    db.expire_all()
    assert db.query(AuditLog).filter(AuditLog.action == "patient_record_viewed").count() == 1
    assert client.get("/patients/99999").status_code == 404
    db.expire_all()
    assert db.query(AuditLog).filter(AuditLog.action == "patient_record_viewed").count() == 1