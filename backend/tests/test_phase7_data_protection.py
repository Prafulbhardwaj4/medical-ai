from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app import main
from app.config import settings
from app.database import Base, get_db
from app.models.consultation import Consultation
from app.models.hospital import Hospital
from app.models.patient import Patient
from app.utils import field_crypto
from app.utils.auth import get_current_doctor
from app.utils.transcript_mask import mask_identifiers


# ---------------------------------------------------------------- field encryption

def test_encrypt_round_trip_and_plain_passthrough(monkeypatch):
    monkeypatch.setattr(settings, "DATA_ENC_KEYS", Fernet.generate_key().decode())
    token = field_crypto.encrypt_value("secret words")
    assert token.startswith(field_crypto.PREFIX) and "secret" not in token
    assert field_crypto.decrypt_value(token) == "secret words"
    assert field_crypto.decrypt_value("an old plain value") == "an old plain value"
    assert field_crypto.encrypt_value(token) == token


def test_no_keys_means_no_encryption(monkeypatch):
    monkeypatch.setattr(settings, "DATA_ENC_KEYS", "")
    assert field_crypto.encrypt_value("hello") == "hello"


def test_rotation_moves_to_newest_key_and_old_key_can_be_dropped(monkeypatch):
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "DATA_ENC_KEYS", old)
    token = field_crypto.encrypt_value("abc")
    monkeypatch.setattr(settings, "DATA_ENC_KEYS", f"{new},{old}")
    assert field_crypto.decrypt_value(token) == "abc"
    rotated = field_crypto.rotate_value(token)
    monkeypatch.setattr(settings, "DATA_ENC_KEYS", new)
    assert field_crypto.decrypt_value(rotated) == "abc"
    assert field_crypto.decrypt_value(token) == field_crypto.UNREADABLE


# ------------------------------------------------------------------ name masking

def test_mask_hides_name_parts_and_phone():
    text_in = "Ramesh Kumar ji, call 98765 43210 or +91-9876543210. Mr kumar has fever."
    out = mask_identifiers(text_in, "Ramesh Kumar", "9876543210")
    assert "Ramesh" not in out and "kumar" not in out.lower().replace("[patient]", "")
    assert "98765" not in out and "fever" in out


def test_mask_leaves_text_alone_without_identifiers():
    assert mask_identifiers("fever for 3 days", "", "") == "fever for 3 days"


# ------------------------------------------------------- hospital separation (3F-1)

@pytest.fixture()
def world():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    db = Session()
    h1 = Hospital(name="One", hospital_code="H1")
    h2 = Hospital(name="Two", hospital_code="H2")
    db.add_all([h1, h2])
    db.commit()
    mine = Patient(patient_uid="P1", url_token="t1", name="Asha Rao", phone="9000000001", age=30, gender="F", hospital_id=h1.id)
    other = Patient(patient_uid="P2", url_token="t2", name="Vikram Das", phone="9000000002", age=40, gender="M", hospital_id=h2.id)
    db.add_all([mine, other])
    db.commit()
    db.add(Consultation(patient_id=mine.id, doctor_id=1, token_number="T1", raw_transcript="Asha said hello"))
    db.commit()

    admin = SimpleNamespace(id=1, title="Dr.", name="Boss", hospital_id=h1.id, role=SimpleNamespace(value="admin"))

    def _db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    main.app.dependency_overrides[get_db] = _db
    main.app.dependency_overrides[get_current_doctor] = lambda: admin
    client = TestClient(main.app, raise_server_exceptions=False)
    yield client, db, mine.id, other.id, admin
    main.app.dependency_overrides.clear()


def test_other_hospitals_patient_is_invisible_to_all_three(world):
    client, db, mine, other, admin = world
    assert client.get(f"/data-rights/patients/{other}/export").status_code == 404
    assert client.put(f"/data-rights/patients/{other}/correct", json={"address": "x"}).status_code == 404
    assert client.post(f"/data-rights/patients/{other}/anonymise", json={"confirm_text": "ANONYMISE P2"}).status_code == 404
    db.expire_all()
    assert db.query(Patient).get(other).name == "Vikram Das"


def test_export_and_correct_work_inside_own_hospital(world):
    client, db, mine, other, admin = world
    r = client.get(f"/data-rights/patients/{mine}/export")
    assert r.status_code == 200 and r.json()["profile"]["name"] == "Asha Rao" and len(r.json()["consultations"]) == 1
    r = client.put(f"/data-rights/patients/{mine}/correct", json={"address": "12 Main Road"})
    assert r.status_code == 200 and r.json()["fields_changed"] == 1
    assert client.put(f"/data-rights/patients/{mine}/correct", json={}).status_code == 400


def test_other_roles_are_refused(world):
    client, db, mine, other, admin = world
    admin.role = SimpleNamespace(value="doctor")
    assert client.get(f"/data-rights/patients/{mine}/export").status_code == 403


def test_anonymise_needs_typed_confirmation_then_strips_identity(world):
    client, db, mine, other, admin = world
    assert client.post(f"/data-rights/patients/{mine}/anonymise", json={"confirm_text": "yes"}).status_code == 400
    r = client.post(f"/data-rights/patients/{mine}/anonymise", json={"confirm_text": "ANONYMISE P1"})
    assert r.status_code == 200
    db.expire_all()
    p = db.query(Patient).get(mine)
    assert p.name == "Anonymised Patient" and p.phone == "0000000000" and p.is_active is False
    c = db.query(Consultation).filter(Consultation.patient_id == mine).first()
    assert c is not None and c.raw_transcript is None
    assert db.query(Patient).get(other).name == "Vikram Das"