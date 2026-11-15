import pytest
from starlette.websockets import WebSocketDisconnect
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
import app.main
from app.main import app
import app.routers.consultations as cons
from app.utils.auth import get_current_doctor, now_ist_naive
from app.models.hospital import Hospital
from app.models.doctor import Doctor, UserRole
from app.models.patient import Patient


@pytest.fixture()
def env(monkeypatch):
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

    async def _fake_stream(audio_q, transcript_q):
        await transcript_q.put({"type": "end"})

    monkeypatch.setattr(cons, "stream_transcribe", _fake_stream)
    import app.routers.consents as consents
    monkeypatch.setattr(consents, "has_recording_consent", lambda db, pid: True)
    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_doctor] = _current
    yield db, state, TestClient(app)
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def _world(db, tier="scale"):
    h = Hospital(name="H", hospital_code="HC1", tier=tier, billing_cycle_start=now_ist_naive())
    db.add(h); db.flush()
    users = {}
    for role in ("doctor", "nurse", "receptionist"):
        d = Doctor(name=role, email=f"{role}@x.in", phone="9", specialization="GP",
                   hashed_password="x", hospital_id=h.id, role=UserRole(role))
        db.add(d); users[role] = d
    p = Patient(url_token="pt1", name="P", phone="9", age=30, gender="M", hospital_id=h.id)
    db.add(p); db.commit()
    return h, users, p


def _ticket(client, state, users, p):
    state["user_id"] = users["doctor"].id
    res = client.post(f"/consultations/ws-ticket/{p.id}")
    assert res.status_code == 200, res.text
    return res.json()["ticket"]


def test_only_doctors_get_a_ticket(env):
    db, state, client = env
    h, users, p = _world(db)
    for role in ("nurse", "receptionist"):
        state["user_id"] = users[role].id
        assert client.post(f"/consultations/ws-ticket/{p.id}").status_code == 403


def test_ticket_refused_when_scribe_not_allowed(env):
    db, state, client = env
    h, users, p = _world(db, tier="foundation")
    state["user_id"] = users["doctor"].id
    res = client.post(f"/consultations/ws-ticket/{p.id}")
    assert res.status_code == 402
    assert res.json()["detail"]["ai_scribe_blocked"] is True


def test_ticket_refused_for_inactive_hospital(env):
    db, state, client = env
    h, users, p = _world(db)
    h.is_active = False
    db.commit()
    state["user_id"] = users["doctor"].id
    assert client.post(f"/consultations/ws-ticket/{p.id}").status_code == 403


def test_ticket_is_single_use(env):
    db, state, client = env
    h, users, p = _world(db)
    t = _ticket(client, state, users, p)
    with client.websocket_connect(f"/consultations/ws/transcribe/{p.id}?ticket={t}") as ws:
        pass
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect(f"/consultations/ws/transcribe/{p.id}?ticket={t}") as ws:
            ws.receive_text()
    assert e.value.code == 4001


def test_two_tickets_in_one_second_are_different(env):
    db, state, client = env
    h, users, p = _world(db)
    assert _ticket(client, state, users, p) != _ticket(client, state, users, p)


def test_connect_rechecks_credit_and_hospital(env):
    db, state, client = env
    h, users, p = _world(db)
    t = _ticket(client, state, users, p)
    h.tier = "foundation"
    db.commit()
    with client.websocket_connect(f"/consultations/ws/transcribe/{p.id}?ticket={t}") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "blocked" and msg["reason"] == "not_included_in_tier"
    h.tier = "scale"
    db.commit()
    t2 = _ticket(client, state, users, p)
    h.is_active = False
    db.commit()
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect(f"/consultations/ws/transcribe/{p.id}?ticket={t2}") as ws:
            ws.receive_text()
    assert e.value.code == 4001


def test_connect_refuses_a_ticket_for_a_non_doctor(env):
    db, state, client = env
    h, users, p = _world(db)
    from app.utils.jwt_compat import jwt
    from app.config import settings
    from datetime import datetime, timedelta
    forged = jwt.encode({"sub": str(users["nurse"].id), "pid": p.id, "typ": "ws_ticket", "jti": "x",
                         "exp": datetime.utcnow() + timedelta(seconds=30)},
                        cons._ws_ticket_key(), algorithm=settings.ALGORITHM)
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect(f"/consultations/ws/transcribe/{p.id}?ticket={forged}") as ws:
            ws.receive_text()
    assert e.value.code == 4001