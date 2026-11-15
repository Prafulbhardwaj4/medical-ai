"""The patient's expected-time banner: a time or a delay, never a queue size."""
from datetime import datetime, time, timedelta

from app.models.checkin import Checkin
from app.models.portal import Appointment, AppointmentStatus, AppointmentType
from app.utils.portal_auth import create_portal_access_token
from app.utils.queue_eta import average_consult_minutes, eta_for_appointment
from app.utils.timezone import ist_today, now_ist_naive

_n = [0]


def at(hour, minute=0):
    return datetime.combine(ist_today(), time(hour, minute))


def make_appt(db, hospital, doctor, account, planned, status=AppointmentStatus.confirmed):
    appt = Appointment(account_id=account.id, hospital_id=hospital.id, doctor_id=doctor.id, type=AppointmentType.scheduled,
                       requested_time=planned, status=status)
    db.add(appt)
    db.commit()
    return appt


def make_checkin(db, hospital, doctor, patient, appt=None, started=None, finished=None, planned=None):
    _n[0] += 1
    c = Checkin(hospital_id=hospital.id, patient_id=patient.id, doctor_id=doctor.id, token_number=f"T-{_n[0]}",
                issue_category="fever", visit_date=ist_today(), portal_appointment_id=appt.id if appt else None,
                booked_time=planned, consult_started_at=started, consult_finished_at=finished)
    db.add(c)
    db.commit()
    return c


def setup(db, make_hospital, make_user, make_patient, make_portal_account):
    h = make_hospital(tier="scale")
    return h, make_user(h, "doctor"), make_portal_account(), make_patient


def test_nothing_is_shown_until_the_doctor_presses_consult(db, make_hospital, make_user, make_patient, make_portal_account):
    h, doc, acct, _ = setup(db, make_hospital, make_user, make_patient, make_portal_account)
    appt = make_appt(db, h, doc, acct, at(10, 6))
    assert eta_for_appointment(db, appt, at(10, 0), avg_minutes=10)["state"] == "hidden"


def test_delay_is_shown_for_back_to_back_consultations_and_absorbed_by_a_gap(db, make_hospital, make_user, make_patient, make_portal_account):
    h, doc, acct, mk = setup(db, make_hospital, make_user, make_patient, make_portal_account)
    p0 = make_appt(db, h, doc, acct, at(9, 0))
    make_checkin(db, h, doc, mk(h), p0, started=at(8, 50), finished=at(9, 0))          # finished
    p1 = make_appt(db, h, doc, acct, at(9, 6))
    make_checkin(db, h, doc, mk(h), p1, started=at(10, 0))                              # in the room right now
    w1 = make_appt(db, h, doc, acct, at(9, 12))
    w2 = make_appt(db, h, doc, acct, at(9, 18))
    w3 = make_appt(db, h, doc, acct, at(12, 0))
    now = at(10, 0)
    r1 = eta_for_appointment(db, w1, now, avg_minutes=10)
    assert r1["state"] == "delayed" and r1["delay_minutes"] == 58
    assert r1["message"].endswith("Please reach the hospital now.")
    r2 = eta_for_appointment(db, w2, now, avg_minutes=10)
    assert r2["message"] == ("Consultations are running about 62 minutes late. Your expected time is about 10:20 AM. "
                             "Reach the hospital by 10:05 AM to avoid any inconvenience.")
    r3 = eta_for_appointment(db, w3, now, avg_minutes=10)   # a long gap before 12:00 absorbs the whole delay
    assert r3["state"] == "on_time"
    assert r3["message"] == "Your appointment is at 12:00 PM. Please reach 15 minutes before."
    assert eta_for_appointment(db, p1, now, avg_minutes=10)["state"] == "in_consultation"
    assert eta_for_appointment(db, p0, now, avg_minutes=10)["state"] == "hidden"


def test_a_late_patient_with_a_free_doctor_is_not_blamed_on_the_doctor(db, make_hospital, make_user, make_patient, make_portal_account):
    h, doc, acct, mk = setup(db, make_hospital, make_user, make_patient, make_portal_account)
    p0 = make_appt(db, h, doc, acct, at(9, 0))
    make_checkin(db, h, doc, mk(h), p0, started=at(9, 0), finished=at(9, 10))
    w = make_appt(db, h, doc, acct, at(9, 30))
    r = eta_for_appointment(db, w, at(10, 0), avg_minutes=10)
    assert r["state"] == "ready" and "Consultations are running" not in r["message"]


def test_small_slips_still_read_on_time(db, make_hospital, make_user, make_patient, make_portal_account):
    h, doc, acct, mk = setup(db, make_hospital, make_user, make_patient, make_portal_account)
    p1 = make_appt(db, h, doc, acct, at(9, 50))
    make_checkin(db, h, doc, mk(h), p1, started=at(9, 50))
    w = make_appt(db, h, doc, acct, at(10, 0))
    r = eta_for_appointment(db, w, at(9, 55), avg_minutes=10)   # expected 10:00 -> 0 minutes late
    assert r["state"] == "on_time"


def test_average_uses_real_history_after_three_consultations(db, make_hospital, make_user, make_patient, make_portal_account):
    h, doc, acct, mk = setup(db, make_hospital, make_user, make_patient, make_portal_account)
    now = now_ist_naive()
    assert average_consult_minutes(db, doc.id, h.id, now) == 10.0
    for i in range(3):
        make_checkin(db, h, doc, mk(h), started=now - timedelta(minutes=60 + i), finished=now - timedelta(minutes=40 + i))
    assert abs(average_consult_minutes(db, doc.id, h.id, now) - 20.0) < 0.01


def test_portal_endpoint_shows_only_own_appointments_and_no_counts(client, db, make_hospital, make_user, make_patient, make_portal_account):
    h, doc, acct, mk = setup(db, make_hospital, make_user, make_patient, make_portal_account)
    other = make_portal_account(phone="9876500001")
    now = now_ist_naive().replace(second=0, microsecond=0)
    p1 = make_appt(db, h, doc, other, now)
    make_checkin(db, h, doc, mk(h), p1, started=now)
    mine = make_appt(db, h, doc, acct, now)
    headers = lambda a: {"Authorization": f"Bearer {create_portal_access_token(a.id)}"}
    r = client.get("/portal/appointments/eta-today", headers=headers(acct))
    assert r.status_code == 200
    body = r.json()
    assert [e["appointment_id"] for e in body] == [mine.id] and body[0]["state"] == "delayed"
    assert set(body[0]) == {"appointment_id", "state", "message", "planned_time", "expected_time", "delay_minutes", "reach_by",
                            "doctor_name", "hospital_name", "patient_name"}
    assert client.get("/portal/appointments/eta-today", headers=headers(other)).json() == []   # the one in the room sees nothing


def test_consult_start_is_recorded_once_and_only_for_the_doctors_own_patient(client, db, make_hospital, make_user, make_patient, auth_headers):
    h = make_hospital(tier="scale")
    doc, other_doc, rec = make_user(h, "doctor"), make_user(h, "doctor"), make_user(h, "receptionist")
    patient = make_patient(h)
    c = make_checkin(db, h, doc, patient)
    r = client.post(f"/consultations/start/{patient.id}", headers=auth_headers(doc))
    assert r.status_code == 200 and r.json() == {"started": True}
    db.expire_all()
    first = db.query(Checkin).get(c.id).consult_started_at
    assert first is not None
    client.post(f"/consultations/start/{patient.id}", headers=auth_headers(doc))
    db.expire_all()
    assert db.query(Checkin).get(c.id).consult_started_at == first
    assert client.post(f"/consultations/start/{patient.id}", headers=auth_headers(other_doc)).json() == {"started": False}
    assert client.post(f"/consultations/start/{patient.id}", headers=auth_headers(rec)).status_code == 403


def test_confirming_the_prescription_records_the_finish_time(client, db, make_hospital, make_user, make_patient, auth_headers):
    import json
    from app.models.consultation import Consultation
    h = make_hospital(tier="scale")
    doc = make_user(h, "doctor")
    patient = make_patient(h)
    c = make_checkin(db, h, doc, patient)
    c.is_paid = True
    k = Consultation(patient_id=patient.id, doctor_id=doc.id, medicines=json.dumps([]), chief_complaint="fever", diagnosis="viral")
    db.add(k)
    db.commit()
    r = client.post(f"/consultations/confirm/{k.id}", headers=auth_headers(doc), json={})
    assert r.status_code == 200, r.text
    db.expire_all()
    c = db.query(Checkin).get(c.id)
    assert c.consult_finished_at is not None and c.consult_started_at is not None
    assert c.consult_started_at <= c.consult_finished_at