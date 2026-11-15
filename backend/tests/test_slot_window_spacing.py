"""A session's patients are spread over the WHOLE session: 10:00 - 12:00 with 10 patients = 12 minutes apart."""
from datetime import timedelta

from app.models.doctor_slot import DoctorSlot
from app.routers.portal_appointments import _estimated_slot_datetime
from app.utils.timezone import now_ist_naive


def _save(client, headers, doctor, morning, capacity=10, custom=None):
    # every weekday, so the test never depends on which day it runs
    return client.post("/doctor-slots/template", headers=headers, json={
        "weekdays": [0, 1, 2, 3, 4, 5, 6], "morning_times": morning, "afternoon_times": [], "evening_times": [],
        "custom_windows": custom or {}, "capacity_mode": "same", "capacity_same": capacity,
        "capacity_morning": capacity, "capacity_afternoon": capacity, "capacity_evening": capacity,
    })


def _tomorrows_slots(db, doctor):
    day = now_ist_naive().date() + timedelta(days=1)
    return {s.slot_time: s for s in db.query(DoctorSlot).filter(DoctorSlot.doctor_id == doctor.id, DoctorSlot.slot_date == day).all()}


def test_a_single_preset_slot_is_a_two_hour_window(client, db, make_hospital, make_user, auth_headers):
    doctor = make_user(make_hospital(), "doctor")
    assert _save(client, auth_headers(doctor), doctor, ["11:00"]).status_code == 200
    slot = _tomorrows_slots(db, doctor)["11:00"]
    assert slot.window_minutes == 120
    gaps = [(_estimated_slot_datetime(slot, n + 1) - _estimated_slot_datetime(slot, n)).total_seconds() / 60 for n in range(1, 10)]
    assert gaps == [12.0] * 9


def test_presets_two_hours_apart_keep_two_hour_windows(client, db, make_hospital, make_user, auth_headers):
    doctor = make_user(make_hospital(), "doctor")
    assert _save(client, auth_headers(doctor), doctor, ["07:00", "09:00", "11:00"]).status_code == 200
    assert {t: s.window_minutes for t, s in _tomorrows_slots(db, doctor).items()} == {"07:00": 120, "09:00": 120, "11:00": 120}


def test_far_apart_slots_are_not_stretched_over_the_gap(client, db, make_hospital, make_user, auth_headers):
    doctor = make_user(make_hospital(), "doctor")
    assert _save(client, auth_headers(doctor), doctor, ["07:00", "11:00"]).status_code == 200
    assert {t: s.window_minutes for t, s in _tomorrows_slots(db, doctor).items()} == {"07:00": 120, "11:00": 120}


def test_close_slots_do_not_overlap_and_custom_windows_still_win(client, db, make_hospital, make_user, auth_headers):
    doctor = make_user(make_hospital(), "doctor")
    assert _save(client, auth_headers(doctor), doctor, ["09:00", "10:00", "10:30"], capacity=4, custom={"10:30": 30}).status_code == 200
    assert {t: s.window_minutes for t, s in _tomorrows_slots(db, doctor).items()} == {"09:00": 60, "10:00": 30, "10:30": 30}