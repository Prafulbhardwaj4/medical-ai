from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.utils.timezone import now_ist_naive


def convert_appointment_to_checkin(db: Session, appt, patient):
    """Turns a paid, confirmed online appointment into the same real
    day-of Checkin/token a walk-in gets — so the patient appears in the
    nurse vitals queue / doctor queue / assistant dashboard all day, tagged
    with its slot time, whether or not the patient has actually arrived
    yet. Token generation no longer waits on appt.arrived_at — that field
    is now only used to compute grace-window/queue-priority once arrival
    actually happens. Idempotent — safe to call more than once for the
    same appointment; a second call (e.g. once arrived_at is later set)
    just refreshes the existing Checkin's priority instead of duplicating
    it."""
    from app.models.checkin import Checkin
    from app.models.hospital import Hospital
    from app.models.portal import AppointmentStatus
    from app.config import settings

    # Grace window + priority ordering: on time (within the grace window of
    # the booked slot) sorts ahead of walk-ins who checked in after the slot
    # start, but behind those already waiting since before it — achieved by
    # sorting on the slot's own start time instead of actual arrival time.
    # Past the grace window, no priority — sorts normally by arrival like
    # any walk-in. Before arrival at all, no priority either — a
    # pre-generated token just sits in the queue at its natural creation
    # order until the patient actually shows up.
    priority_time = None
    if appt.arrived_at:
        grace_cutoff = appt.requested_time + timedelta(minutes=settings.PORTAL_GRACE_WINDOW_MINUTES)
        on_time = appt.arrived_at <= grace_cutoff
        priority_time = appt.requested_time if on_time else None

    existing = db.query(Checkin).filter(Checkin.portal_appointment_id == appt.id).first()
    if existing:
        if existing.queue_priority_time != priority_time:
            existing.queue_priority_time = priority_time
            db.commit()
            db.refresh(existing)
        return existing

    hospital = db.query(Hospital).filter(Hospital.id == appt.hospital_id).first()
    hospital_code = hospital.hospital_code if hospital else "GEN"

    from app.routers.patients import generate_token_number, pick_random_nurse
    token = generate_token_number(db, appt.hospital_id, hospital_code)

    # Assistant-away fallback gate: an online booking only ever goes
    # straight to the doctor if no nurse/assistant is present at all —
    # reception's system never gets a free choice here the way it does for
    # walk-ins.
    nurse = pick_random_nurse(db, appt.hospital_id, appt.doctor_id) if appt.doctor_id else None

    # generate_token_number's check-then-generate isn't airtight under real
    # concurrency — the DB's unique constraint on token_number is the actual
    # hard backstop. Retry on the IntegrityError it raises rather than
    # letting a genuine race surface as a raw failure.
    max_token_attempts = 5
    for attempt in range(max_token_attempts):
        checkin = Checkin(
            hospital_id=appt.hospital_id,
            patient_id=patient.id,
            token_number=token,
            issue_category=appt.notes or "Online booking",
            doctor_id=appt.doctor_id,
            created_by=None,  # system handoff, no staff actor
            visit_date=now_ist_naive().date(),
            consultation_fee=appt.fee_amount,
            is_paid=True,  # already paid on the portal — this function only ever runs for payment_status == "paid" appointments. Leaving this unset defaulted to False, which silently hid every online patient from the doctor/assistant queue (both filter on is_paid) until reception re-marked them paid a second time.
            payment_method=appt.payment_method,  # was never propagated — day-end/revenue bucket by this and silently dropped the fee without it
            paid_at=appt.paid_at,  # the actual moment reception collected it, not whenever this Checkin object happens to get created (could be a different calendar day)
            source="online",
            portal_appointment_id=appt.id,
            booked_time=appt.requested_time,
            queue_priority_time=priority_time,
            nurse_id=nurse.id if nurse else None,
            vitals_status="pending" if nurse else "none",
        )
        db.add(checkin)
        try:
            db.flush()
            break
        except IntegrityError:
            db.rollback()
            if attempt == max_token_attempts - 1:
                raise
            token = generate_token_number(db, appt.hospital_id, hospital_code)

    if appt.reschedule_balance_due:
        # Extra owed from an earlier reschedule-to-a-costlier-doctor — no
        # live payment gateway to have charged this online mid-flow, so it
        # collects here the same way any other OPD balance does.
        from app.models.opd_charge import OpdCharge
        db.add(OpdCharge(
            checkin_id=checkin.id, patient_id=patient.id, hospital_id=appt.hospital_id,
            description="Reschedule fee difference (switched to a higher-fee doctor)",
            amount=appt.reschedule_balance_due, quantity=1, added_by=None,
        ))
        appt.reschedule_balance_due = None

    appt.status = AppointmentStatus.completed  # booking's job is done — the real visit now lives on the Checkin
    db.commit()
    db.refresh(checkin)
    return checkin


def sweep_todays_online_checkins(db: Session, hospital_id: int) -> None:
    """No background scheduler in this codebase — same lazy-sweep pattern
    used elsewhere (_release_abandoned_holds, _expire_stale_pending_reviews).
    Converts EVERY paid, confirmed, already-linked-to-a-real-patient
    appointment for today into a real Checkin/token the moment anyone loads
    a queue view — this is the 'morning batch' generation: a token no
    longer waits on the patient tapping 'I've arrived'. Idempotent per
    appointment, so this can run on every page load with no duplicate
    tokens; arrived_at (whenever it's later set) only refreshes queue
    priority on the already-generated Checkin. A genuinely new patient's
    booking converts separately, the moment reception adds them as a real
    Patient — see patients.py:_auto_complete_matching_appointment."""
    from app.models.portal import Appointment, AppointmentStatus, PatientProfileLink

    today_start = datetime.combine(now_ist_naive().date(), datetime.min.time())
    today_end = today_start + timedelta(days=1)

    appts = db.query(Appointment).filter(
        Appointment.hospital_id == hospital_id,
        Appointment.status == AppointmentStatus.confirmed,
        Appointment.payment_status == "paid",
        Appointment.profile_link_id.isnot(None),
        Appointment.requested_time >= today_start,
        Appointment.requested_time < today_end,
    ).all()

    for appt in appts:
        link = db.query(PatientProfileLink).filter(PatientProfileLink.id == appt.profile_link_id).first()
        if link and link.patient:
            convert_appointment_to_checkin(db, appt, link.patient)