"""Core tests: sign-in, sessions, hospital separation, role gates, public safety."""
import pytest

from app.models.doctor import Doctor
from app.models.hospital import Hospital
from app.utils.portal_auth import create_portal_access_token

PW = "Str0ng!Pass#1"


# ------------------------------------------------------------------ health
def test_health_live_never_needs_the_database(client):
    r = client.get("/health/live")
    assert r.status_code == 200


def test_health_checks_the_database(client):
    r = client.get("/health")
    assert r.status_code == 200


def test_health_returns_503_when_the_database_is_down(client, monkeypatch):
    import app.main as main

    def _boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(main, "SessionLocal", _boom, raising=False)
    monkeypatch.setattr(main.engine, "connect", _boom)
    r = client.get("/health")
    assert r.status_code == 503


# ------------------------------------------------------------ sign-in / session
def test_login_success_wrong_password_and_inactive_account(client, captcha, make_hospital, make_user, db):
    h = make_hospital("H1")
    make_user(h, "admin", "ok@h1.test", PW)
    good = client.post("/auth/login", json={"email": "ok@h1.test", "password": PW, **captcha})
    assert good.status_code == 200 and good.json()["status"] == "success"
    bad = client.post("/auth/login", json={"email": "ok@h1.test", "password": "Wrong-Pass9", **captcha})
    assert bad.status_code == 401
    user = db.query(Doctor).filter(Doctor.email == "ok@h1.test").first()
    user.is_active = False
    db.commit()
    off = client.post("/auth/login", json={"email": "ok@h1.test", "password": PW, **captcha})
    assert off.status_code in (401, 403)


def test_protected_routes_need_a_token(client):
    for path in ("/patients/", "/admissions/active", "/consultations/today"):
        assert client.get(path).status_code in (401, 403)
    assert client.get("/patients/", headers={"Authorization": "Bearer not-a-token"}).status_code in (401, 403)


def test_logout_makes_the_token_useless(client, two_hospitals, auth_headers):
    user = two_hospitals["users"]["h1"]["receptionist"]
    headers = auth_headers(user)
    assert client.get("/patients/", headers=headers).status_code == 200
    assert client.post("/auth/logout", headers=headers).status_code == 200
    assert client.get("/patients/", headers=headers).status_code in (401, 403)


def test_portal_token_does_not_open_staff_routes(client, make_portal_account):
    account = make_portal_account("9876500777", PW)
    headers = {"Authorization": f"Bearer {create_portal_access_token(account.id)}"}
    assert client.get("/patients/", headers=headers).status_code in (401, 403)


def test_inactive_hospital_is_locked_out(client, two_hospitals, auth_headers, db):
    user = two_hospitals["users"]["h1"]["receptionist"]
    headers = auth_headers(user)
    assert client.get("/patients/", headers=headers).status_code == 200
    h = db.query(Hospital).filter(Hospital.id == two_hospitals["h1"].id).first()
    h.is_active = False
    db.commit()
    assert client.get("/patients/", headers=headers).status_code in (401, 403)


# ------------------------------------------------------- hospital separation
FOREIGN_PATIENT_PATHS = [
    ("/patients/{pid}", "doctor"),
    ("/patients/{pid}/documents", "doctor"),
    ("/patients/{pid}/allergies", "doctor"),
    ("/patients/{pid}/test-orders", "doctor"),
    ("/patients/{pid}/pending-tasks", "receptionist"),
    ("/consultations/history/{pid}", "doctor"),
]


@pytest.mark.parametrize("template,role", FOREIGN_PATIENT_PATHS)
def test_a_patient_of_another_hospital_is_never_returned(client, two_hospitals, auth_headers, make_patient, template, role):
    foreign = make_patient(two_hospitals["h2"], "Foreign Patient")
    own = make_patient(two_hospitals["h1"], "Own Patient")
    headers = auth_headers(two_hospitals["users"]["h1"][role])
    r = client.get(template.format(pid=foreign.id), headers=headers)
    assert r.status_code == 404, f"{template}: foreign patient answered {r.status_code}"
    assert "Foreign Patient" not in r.text
    assert client.get(template.format(pid=own.id), headers=headers).status_code != 404


def test_patient_list_shows_only_own_hospital(client, two_hospitals, auth_headers, make_patient):
    make_patient(two_hospitals["h1"], "Alpha One")
    make_patient(two_hospitals["h2"], "Beta Two")
    r = client.get("/patients/", headers=auth_headers(two_hospitals["users"]["h1"]["receptionist"]))
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    assert "Alpha One" in names and "Beta Two" not in names


# ------------------------------------------------------------------ role gates
@pytest.mark.parametrize("role", ["pharmacy", "lab"])
def test_pharmacy_and_lab_cannot_open_a_patient_record(client, two_hospitals, auth_headers, make_patient, role):
    patient = make_patient(two_hospitals["h1"], "Private Person")
    r = client.get(f"/patients/{patient.id}", headers=auth_headers(two_hospitals["users"]["h1"][role]))
    assert r.status_code == 403
    assert "Private Person" not in r.text


@pytest.mark.parametrize("role", ["doctor", "receptionist", "nurse", "admin"])
def test_clinical_and_front_desk_roles_can_open_a_patient_record(client, two_hospitals, auth_headers, make_patient, role):
    patient = make_patient(two_hospitals["h1"], "Visible Person")
    r = client.get(f"/patients/{patient.id}", headers=auth_headers(two_hospitals["users"]["h1"][role]))
    assert r.status_code == 200 and r.json()["name"] == "Visible Person"


# ---------------------------------------------------------- platform safety
def test_security_headers_are_on_every_api_response(client):
    r = client.get("/health/live")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "permissions-policy" in r.headers


def test_oversized_request_body_is_refused(client):
    r = client.post("/auth/login", content=b"x" * (13 * 1024 * 1024), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_create_superadmin_route_is_off_without_a_key(client):
    r = client.post("/admin/create-superadmin", json={"name": "X Y", "email": "x@y.test", "phone": "9999999999", "password": PW})
    assert r.status_code == 404


def test_chat_upload_needs_a_login(client):
    r = client.post("/chat/upload", files={"file": ("a.png", b"\x89PNG\r\n\x1a\n" + b"0" * 20, "image/png")})
    assert r.status_code in (401, 403)


def test_unknown_public_verify_link_answers_cleanly(client):
    r = client.get("/consultations/verify/NO-SUCH-TOKEN", params={"hash": "bad"})
    assert r.status_code in (200, 400, 403, 404)
    if r.status_code == 200:
        assert r.json().get("valid") is False
    assert "Traceback" not in r.text