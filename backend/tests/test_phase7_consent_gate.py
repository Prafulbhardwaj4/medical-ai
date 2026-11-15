from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.routers import consents, consultations
from app.models.consent_record import ConsentRecord


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    ConsentRecord.__table__.create(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _add(session, patient_id, version):
    session.add(ConsentRecord(hospital_id=1, subject_type="patient", subject_id=patient_id,
                              purpose="ai_recording", notice_version=version, recorded_by=1))
    session.commit()


def test_no_record_means_no_consent(session):
    assert consents.has_recording_consent(session, 5) is False


def test_current_version_counts_other_patient_or_old_version_does_not(session):
    _add(session, 5, consents.NOTICE_VERSION)
    _add(session, 6, "old-version")
    assert consents.has_recording_consent(session, 5) is True
    assert consents.has_recording_consent(session, 6) is False
    assert consents.has_recording_consent(session, 7) is False


class _Q:
    def __init__(self, item): self.item = item
    def filter(self, *a, **k): return self
    def first(self): return self.item


class _DB:
    def __init__(self, item): self.item = item
    def query(self, *a, **k): return _Q(self.item)


def test_ws_ticket_refused_without_consent(monkeypatch):
    monkeypatch.setattr(consents, "has_recording_consent", lambda db, pid: False)
    doctor = SimpleNamespace(id=1, hospital_id=1, role=SimpleNamespace(value="doctor"))
    with pytest.raises(HTTPException) as e:
        consultations.create_ws_ticket(5, current_doctor=doctor, db=_DB(SimpleNamespace(id=5)))
    assert e.value.status_code == 409


def test_ws_ticket_issued_with_consent(monkeypatch):
    monkeypatch.setattr(consents, "has_recording_consent", lambda db, pid: True)
    monkeypatch.setattr(consultations, "get_ai_scribe_status", lambda db, hospital: {"allowed": True, "reason": None})
    doctor = SimpleNamespace(id=1, hospital_id=1, role=SimpleNamespace(value="doctor"))
    out = consultations.create_ws_ticket(5, current_doctor=doctor, db=_DB(SimpleNamespace(id=5, is_active=True, tier="scale")))
    assert out["ticket"]


def test_consent_status_endpoint_rejects_non_recording_roles():
    doctor = SimpleNamespace(role=SimpleNamespace(value="pharmacy"), hospital_id=1)
    with pytest.raises(HTTPException) as e:
        consents.recording_consent_status(5, db=_DB(SimpleNamespace(id=5)), current_doctor=doctor)
    assert e.value.status_code == 403


def test_consent_status_endpoint_reports(monkeypatch):
    monkeypatch.setattr(consents, "has_recording_consent", lambda db, pid: True)
    doctor = SimpleNamespace(role=SimpleNamespace(value="doctor"), hospital_id=1)
    out = consents.recording_consent_status(5, db=_DB(SimpleNamespace(id=5)), current_doctor=doctor)
    assert out["recorded"] is True
    with pytest.raises(HTTPException) as e:
        consents.recording_consent_status(5, db=_DB(None), current_doctor=doctor)
    assert e.value.status_code == 404