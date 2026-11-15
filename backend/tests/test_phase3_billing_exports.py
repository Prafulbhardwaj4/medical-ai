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
    h = Hospital(name="H", hospital_code="HC1", tier="scale")
    db.add(h); db.flush()
    users = {}
    for role in ("admin", "sub_admin", "receptionist", "pharmacy", "doctor", "nurse", "lab"):
        d = Doctor(name=role, email=f"{role}@x.in", phone="9", specialization="GP",
                   hashed_password="x", hospital_id=h.id, role=UserRole(role))
        db.add(d); users[role] = d
    db.commit()
    yield db, state, users, h, TestClient(app)
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def test_daily_export_roles_and_audit(env):
    db, state, users, h, client = env
    for role in ("receptionist", "pharmacy", "doctor", "nurse", "lab"):
        state["user_id"] = users[role].id
        assert client.get("/billing/revenue-history/daily/export").status_code == 403
    assert db.query(AuditLog).filter(AuditLog.action == "billing_report_exported").count() == 0
    for role in ("admin", "sub_admin"):
        state["user_id"] = users[role].id
        res = client.get("/billing/revenue-history/daily/export")
        assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    rows = db.query(AuditLog).filter(AuditLog.action == "billing_report_exported").all()
    assert len(rows) == 2
    assert json.loads(rows[0].details)["report"] == "revenue_history_daily"
    assert rows[0].hospital_id == h.id


def test_day_end_export_roles_and_audit(env):
    db, state, users, h, client = env
    for role in ("pharmacy", "doctor", "nurse", "lab"):
        state["user_id"] = users[role].id
        assert client.get("/billing/day-end-summary/export").status_code == 403
    assert db.query(AuditLog).filter(AuditLog.action == "billing_report_exported").count() == 0
    state["user_id"] = users["receptionist"].id
    res = client.get("/billing/day-end-summary/export")
    assert res.status_code == 200
    row = db.query(AuditLog).filter(AuditLog.action == "billing_report_exported").one()
    assert json.loads(row.details)["report"] == "day_end_summary"