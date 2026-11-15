"""When will this online appointment really be seen?  (the patient's expected-time banner)

Rules:
 * Nothing is shown until the doctor has pressed Consult for any patient today.
 * Each waiting patient's expected start = the later of (their planned time, the previous waiting patient's
   expected finish). A gap between consultations absorbs a delay; back-to-back consultations carry it forward.
 * The patient only ever sees a time or a delay in minutes - never how many patients are ahead.
"""
import logging
from datetime import timedelta

from app.models.checkin import Checkin
from app.models.consultation import Consultation
from app.models.doctor_slot import DoctorSlot
from app.models.portal import Appointment, AppointmentStatus
from app.utils.timezone import ist_day_bounds, now_ist_naive

logger = logging.getLogger(__name__)

ON_TIME_TOLERANCE_MIN = 5   # up to this many minutes late still reads "on time"
REACH_EARLY_MIN = 15        # ask the patient to be at the hospital this long before their time
DEFAULT_CONSULT_MIN = 10
LOOKBACK_DAYS = 30
MIN_SAMPLES = 3
ACTIVE_STATUSES = (AppointmentStatus.booked, AppointmentStatus.confirmed)


def _clock(dt):
    return dt.strftime("%I:%M %p").lstrip("0")


def _to_minute(dt):
    return (dt + timedelta(seconds=30)).replace(second=0, microsecond=0)


def _scheduled_minutes(db, doctor_id, day):
    """Minutes per patient the doctor's own slot pattern assumes (used until there is real history)."""
    slots = db.query(DoctorSlot).filter(DoctorSlot.doctor_id == doctor_id, DoctorSlot.slot_date == day).all()
    per = [s.window_minutes / s.capacity for s in slots if s.capacity and s.window_minutes]
    if not per:
        return float(DEFAULT_CONSULT_MIN)
    return float(min(30, max(5, sum(per) / len(per))))


def average_consult_minutes(db, doctor_id, hospital_id, now):
    """Doctor's real average over the last 30 days; falls back to the slot pattern until 3 consultations exist."""
    rows = db.query(Checkin.consult_started_at, Checkin.consult_finished_at).filter(
        Checkin.doctor_id == doctor_id, Checkin.hospital_id == hospital_id,
        Checkin.consult_started_at != None, Checkin.consult_finished_at != None,  # noqa: E711
        Checkin.consult_finished_at >= now - timedelta(days=LOOKBACK_DAYS),
    ).all()
    mins = [(f - s).total_seconds() / 60 for s, f in rows]
    mins = [m for m in mins if 1 <= m <= 120]
    if len(mins) >= MIN_SAMPLES:
        return sum(mins) / len(mins)
    return _scheduled_minutes(db, doctor_id, now.date())


def build_queue(db, doctor_id, hospital_id, now):
    """Today's people for this doctor as dicts: appt_id, planned, state (done | in_consult | waiting), started_at."""
    day_start, day_end = ist_day_bounds(now.date())
    checkins = db.query(Checkin).filter(
        Checkin.doctor_id == doctor_id, Checkin.hospital_id == hospital_id, Checkin.visit_date == now.date(),
    ).all()
    appt_ids = [c.portal_appointment_id for c in checkins if c.portal_appointment_id]
    planned_by_appt = {}
    if appt_ids:
        planned_by_appt = {a.id: a.requested_time for a in db.query(Appointment).filter(Appointment.id.in_(appt_ids)).all()}
    by_patient = {}
    for k in db.query(Consultation).filter(
        Consultation.doctor_id == doctor_id, Consultation.is_voided == False,  # noqa: E712
        Consultation.created_at >= day_start, Consultation.created_at < day_end,
    ).all():
        by_patient.setdefault(k.patient_id, []).append(k)

    items = []
    for c in checkins:
        if c.emergency_status == "holding":
            continue  # still in the emergency ward, not in the doctor's queue
        since = c.returned_at if (c.is_returned and c.returned_at) else None
        ks = [k for k in by_patient.get(c.patient_id, []) if since is None or k.created_at > since]

        def _after(dt):
            return dt is not None and (since is None or dt > since)

        finished = _after(c.consult_finished_at) or any(
            k.token_number and (k.token_number == c.token_number or k.token_number.startswith(c.token_number + "-")) for k in ks)
        started_at = c.consult_started_at if _after(c.consult_started_at) else (min((k.created_at for k in ks), default=None))
        planned = since or planned_by_appt.get(c.portal_appointment_id) or c.booked_time or c.queue_priority_time or c.created_at
        items.append({
            "appt_id": c.portal_appointment_id, "planned": planned, "started_at": started_at,
            "state": "done" if finished else ("in_consult" if started_at else "waiting"),
        })

    have_checkin = {i["appt_id"] for i in items if i["appt_id"]}
    for a in db.query(Appointment).filter(
        Appointment.doctor_id == doctor_id, Appointment.hospital_id == hospital_id,
        Appointment.status.in_(ACTIVE_STATUSES),
        Appointment.requested_time >= day_start, Appointment.requested_time < day_end,
        Appointment.no_show_detected_at == None,  # noqa: E711
    ).all():
        if a.id not in have_checkin:
            items.append({"appt_id": a.id, "planned": a.requested_time, "started_at": None, "state": "waiting"})
    return items


def simulate(items, avg_minutes, now):
    """Fills expected_start / blocked on every waiting item (see the module rules)."""
    avg = timedelta(minutes=avg_minutes)
    cursor = now
    in_room = False
    for i in items:
        if i["state"] == "in_consult":
            in_room = True
            cursor = max(cursor, (i["started_at"] or now) + avg)
    for i in sorted((x for x in items if x["state"] == "waiting"), key=lambda x: (x["planned"], x["appt_id"] or 0)):
        i["blocked"] = in_room or cursor > now   # somebody is being seen / waiting ahead of this person
        i["expected_start"] = max(i["planned"], cursor)
        cursor = i["expected_start"] + avg
    return items


def eta_for_appointment(db, appt, now=None, avg_minutes=None):
    """Banner content for one appointment: {appointment_id, state, message, planned_time, expected_time, delay_minutes, reach_by}.
    state: hidden | on_time | delayed | ready | in_consultation."""
    now = now or now_ist_naive()
    out = {"appointment_id": appt.id, "state": "hidden"}
    if appt.status not in ACTIVE_STATUSES or not appt.doctor_id or appt.requested_time.date() != now.date():
        return out
    items = build_queue(db, appt.doctor_id, appt.hospital_id, now)
    mine = next((i for i in items if i["appt_id"] == appt.id), None)
    if mine is None or mine["state"] == "done":
        return out
    if mine["state"] == "in_consult":
        out["state"] = "in_consultation"
        return out
    if not any(i["state"] in ("done", "in_consult") for i in items):
        return out  # the doctor has not started yet
    if avg_minutes is None:
        avg_minutes = average_consult_minutes(db, appt.doctor_id, appt.hospital_id, now)
    simulate(items, avg_minutes, now)

    planned = _to_minute(mine["planned"])
    expected = _to_minute(mine["expected_start"])
    delay = int((expected - planned).total_seconds() // 60)
    reach_by = expected - timedelta(minutes=REACH_EARLY_MIN)
    out.update(planned_time=planned.isoformat(), expected_time=expected.isoformat(), delay_minutes=max(delay, 0), reach_by=max(reach_by, now).isoformat())
    if delay <= ON_TIME_TOLERANCE_MIN:
        out["state"] = "on_time"
        out["message"] = (f"Your appointment is at {_clock(planned)}. Please reach the hospital now." if reach_by <= now
                          else f"Your appointment is at {_clock(planned)}. Please reach {REACH_EARLY_MIN} minutes before.")
    elif not mine["blocked"]:
        out["state"] = "ready"  # nobody is ahead: the doctor is waiting for this patient
        out["message"] = "The doctor is ready to see you. Please reach the hospital now."
    else:
        out["state"] = "delayed"
        tail = "Please reach the hospital now." if reach_by <= now else f"Reach the hospital by {_clock(reach_by)} to avoid any inconvenience."
        out["message"] = f"Consultations are running about {delay} minutes late. Your expected time is about {_clock(expected)}. {tail}"
    return out


def etas_for_account(db, account, now=None):
    """Banner entries for every active appointment this account has today (never raises: the banner is optional)."""
    now = now or now_ist_naive()
    result = []
    for a in account.appointments:
        if a.status not in ACTIVE_STATUSES or a.requested_time.date() != now.date():
            continue
        try:
            result.append(eta_for_appointment(db, a, now))
        except Exception:
            logger.exception("expected-time calculation failed for appointment %s", a.id)
    return result