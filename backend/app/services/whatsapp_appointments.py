"""Appointment WhatsApp messages: confirmation, 24-hour reminder, token message, cancelled/rescheduled.

The TEXT of every message is written only in services/whatsapp_messages.py. This file decides WHEN each
message is created and for whom. Every message carries appointment_id, so a cancellation or reschedule can
find the not-yet-sent ones and cancel them.

All functions here are safe to call from a business flow: they run inside a savepoint, never raise, and a
failure only means that the messages were not added (the booking / cancellation itself is untouched).
Pass commit=False when the caller commits right afterwards."""
import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.models.checkin import Checkin
from app.models.doctor import Doctor
from app.models.hospital import Hospital
from app.models.portal import Appointment, PatientAccount, PatientProfileLink
from app.models.whatsapp_message import WhatsappMessage
from app.services import whatsapp_messages as wa
from app.utils.timezone import now_ist_naive

logger = logging.getLogger("whatsapp")

REMINDER_BEFORE = timedelta(hours=24)   # reminder is due 24 hours before the appointment
TOKEN_BEFORE = timedelta(minutes=30)    # token message is due 30 minutes before the appointment
TOKEN_VALID_AFTER = timedelta(hours=3)  # an unsent token message expires 3 hours after the appointment time
# Messages of an appointment that stop making sense when it is cancelled or moved:
TIMED_KEYS = (wa.T_APPT_CONFIRMED, wa.T_APPT_REMINDER, wa.T_VISIT_TOKEN)


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------
def _context(db: Session, appt: Appointment):
    hospital = db.query(Hospital).filter(Hospital.id == appt.hospital_id).first()
    doctor = db.query(Doctor).filter(Doctor.id == appt.doctor_id).first() if appt.doctor_id else None
    account = db.query(PatientAccount).filter(PatientAccount.id == appt.account_id).first()
    patient = None
    if appt.profile_link_id:
        link = db.query(PatientProfileLink).filter(PatientProfileLink.id == appt.profile_link_id).first()
        patient = link.patient if link else None
    name = patient.name if patient else (appt.new_patient_name or "Patient")
    return hospital, doctor, account, patient, name


def _doctor_name(doctor) -> str:
    return f"{doctor.title or ''} {doctor.name}".strip() if doctor else "-"


def _common(appt, account, patient, name, created_by):
    return dict(
        hospital_id=appt.hospital_id, recipient_kind="patient", recipient_id=patient.id if patient else None,
        recipient_name=name, recipient_role="patient", recipient_phone=account.phone,
        visibility=wa.VIS_ALL, created_by=created_by, appointment_id=appt.id,
    )


def _expiry(when, now, extra=timedelta(0)):
    return max(when + extra, now + timedelta(days=1))


def _token_for(db: Session, appt: Appointment, hospital):
    """(token_number, checkin or None) of this appointment's visit. Order: the real check-in's token; else the
    token already reserved by an earlier token message (when nobody has used it); else a new one is generated.
    convert_appointment_to_checkin() takes the reserved token, so the number in the message is the real one."""
    checkin = db.query(Checkin).filter(Checkin.portal_appointment_id == appt.id).first()
    if checkin:
        return checkin.token_number, checkin
    reserved = reserved_token_for_appointment(db, appt.id)
    if reserved:
        return reserved, None
    from app.routers.patients import generate_token_number
    code = hospital.hospital_code if hospital else "GEN"
    while True:
        token = generate_token_number(db, appt.hospital_id, code)
        if not db.query(WhatsappMessage).filter(WhatsappMessage.token_number == token).first():
            return token, None


def reserved_token_for_appointment(db: Session, appointment_id: int):
    """Token number promised in a token message of this appointment that has no check-in yet, else None."""
    row = (db.query(WhatsappMessage)
           .filter(WhatsappMessage.appointment_id == appointment_id, WhatsappMessage.template_key == wa.T_VISIT_TOKEN,
                   WhatsappMessage.token_number.isnot(None), WhatsappMessage.status != "cancelled")
           .order_by(WhatsappMessage.id.desc()).first())
    if row and not db.query(Checkin).filter(Checkin.token_number == row.token_number).first():
        return row.token_number
    return None


def _room(db: Session, appt: Appointment, doctor, checkin) -> str:
    if checkin is not None and checkin.doctor_room:
        return checkin.doctor_room
    if doctor is None or appt.requested_time.date() != now_ist_naive().date():
        return "-"  # the doctor's room is only known on the day itself
    from app.routers.patients import get_doctor_current_room
    return get_doctor_current_room(db, doctor.id, appt.hospital_id) or "-"


def _token_text(db, appt, hospital, doctor, patient, name, token, checkin) -> str:
    return wa.build_visit_token(
        patient_name=name, hospital_name=hospital.name if hospital else "", token_number=token,
        doctor_name=_doctor_name(doctor), speciality=getattr(doctor, "specialization", None) if doctor else None,
        room=_room(db, appt, doctor, checkin), visit_datetime=appt.requested_time,
        patient_uid=patient.patient_uid if patient else None, hospital_mobile_number=wa.hospital_mobile(hospital),
    )


# ---------------------------------------------------------------------------
# The three messages of a new (or rescheduled) appointment
# ---------------------------------------------------------------------------
def _add_booking_messages(db: Session, appt: Appointment, created_by=None) -> None:
    hospital, doctor, account, patient, name = _context(db, appt)
    if account is None or not (account.phone or "").strip():
        return
    now = now_ist_naive()
    when = appt.requested_time
    common = _common(appt, account, patient, name, created_by)
    hname = hospital.name if hospital else ""

    # 1) Confirmation (template 5): due immediately, no token number in it.
    wa.enqueue_message(
        db, template_key=wa.T_APPT_CONFIRMED, expires_at=_expiry(when, now),
        text=wa.build_appointment_confirmed(patient_name=name, hospital_name=hname, appt_datetime=when,
                                            doctor_name=_doctor_name(doctor),
                                            speciality=getattr(doctor, "specialization", None) if doctor else None),
        **common)

    # 2) 24-hour reminder (template 6): due 24 h before; NOT created when booked less than 24 h ahead.
    if when - now >= REMINDER_BEFORE:
        wa.enqueue_message(
            db, template_key=wa.T_APPT_REMINDER, due_at=when - REMINDER_BEFORE, expires_at=_expiry(when, now),
            text=wa.build_appointment_reminder(patient_name=name, hospital_name=hname, appt_datetime=when,
                                               doctor_name=_doctor_name(doctor)), **common)

    # 3) Token message (template 3): due 30 min before (or at once if that time has passed). The token is
    #    generated now if the visit has none yet, and is the same number the real check-in will get.
    token, checkin = _token_for(db, appt, hospital)
    wa.enqueue_message(
        db, template_key=wa.T_VISIT_TOKEN, due_at=when - TOKEN_BEFORE, expires_at=_expiry(when, now, TOKEN_VALID_AFTER),
        text=_token_text(db, appt, hospital, doctor, patient, name, token, checkin),
        token_number=token, checkin_id=checkin.id if checkin else None, **common)


def _finish(db: Session, commit: bool) -> None:
    if commit:
        db.commit()


def queue_appointment_messages(db: Session, appt: Appointment, *, created_by=None, commit=True) -> bool:
    """A new online / phone-booked appointment: confirmation + reminder + token message."""
    try:
        db.flush()
        with db.begin_nested():
            _add_booking_messages(db, appt, created_by)
        _finish(db, commit)
        return True
    except Exception:
        logger.exception("Could not queue the appointment messages")
        _undo_partial(db, commit)
        return False


def _undo_partial(db: Session, commit: bool) -> None:
    if commit:
        try:
            db.rollback()
        except Exception:
            pass


def _add_cancelled_message(db, appt, old_time, doctor, rescheduled, created_by) -> None:
    hospital, _d, account, patient, name = _context(db, appt)
    if account is None or not (account.phone or "").strip():
        return
    wa.enqueue_message(
        db, template_key=wa.T_APPT_CANCELLED,
        text=wa.build_appointment_cancelled(
            patient_name=name, hospital_name=hospital.name if hospital else "", old_datetime=old_time,
            doctor_name=_doctor_name(doctor), rescheduled=rescheduled, hospital_mobile_number=wa.hospital_mobile(hospital)),
        **_common(appt, account, patient, name, created_by))


def queue_appointment_cancelled(db: Session, appt: Appointment, *, send_message=True, created_by=None, commit=True) -> bool:
    """Cancellation. Unsent confirmation / reminder / token messages become Cancelled. The 'appointment cancelled'
    message (template 7) is only added when the HOSPITAL cancelled (its text says so); a patient's own
    cancellation or an old booking that simply lapsed passes send_message=False."""
    try:
        db.flush()
        with db.begin_nested():
            wa.cancel_unsent(db, appointment_id=appt.id, template_keys=TIMED_KEYS)
            if send_message:
                doctor = db.query(Doctor).filter(Doctor.id == appt.doctor_id).first() if appt.doctor_id else None
                _add_cancelled_message(db, appt, appt.requested_time, doctor, False, created_by)
        _finish(db, commit)
        return True
    except Exception:
        logger.exception("Could not queue the appointment cancelled message")
        _undo_partial(db, commit)
        return False


def queue_appointment_rescheduled(db: Session, appt: Appointment, old_time, *, old_doctor_id=None,
                                  created_by=None, commit=True) -> bool:
    """The appointment moved to a new time (and maybe a new doctor). The OLD appointment gets template 7 with
    the reschedule line and its unsent messages are cancelled; the new time is treated as a NEW appointment:
    its own confirmation, reminder and token message."""
    try:
        db.flush()
        with db.begin_nested():
            wa.cancel_unsent(db, appointment_id=appt.id, template_keys=TIMED_KEYS)
            old_id = old_doctor_id if old_doctor_id is not None else appt.doctor_id
            old_doctor = db.query(Doctor).filter(Doctor.id == old_id).first() if old_id else None
            _add_cancelled_message(db, appt, old_time, old_doctor, True, created_by)
            _add_booking_messages(db, appt, created_by)
        _finish(db, commit)
        return True
    except Exception:
        logger.exception("Could not queue the appointment rescheduled messages")
        _undo_partial(db, commit)
        return False


# ---------------------------------------------------------------------------
# Patient arrived: the token message becomes due at once (same message, same token)
# ---------------------------------------------------------------------------
def release_token_message(db: Session, appt: Appointment, *, created_by=None, commit=True) -> bool:
    """Reception (or the patient) marked the appointment as arrived. The waiting token message becomes due now.
    If the visit has no token yet it is generated; if the message does not exist (older booking) it is created."""
    try:
        db.flush()
        with db.begin_nested():
            hospital, doctor, account, patient, name = _context(db, appt)
            if account is None or not (account.phone or "").strip():
                return False
            now = now_ist_naive()
            wa.cancel_unsent(db, appointment_id=appt.id, template_keys=(wa.T_APPT_REMINDER,))  # no longer needed
            token, checkin = _token_for(db, appt, hospital)
            text = _token_text(db, appt, hospital, doctor, patient, name, token, checkin)
            row = (db.query(WhatsappMessage)
                   .filter(WhatsappMessage.appointment_id == appt.id, WhatsappMessage.template_key == wa.T_VISIT_TOKEN,
                           WhatsappMessage.status.in_(wa.OPEN_STATUSES))
                   .order_by(WhatsappMessage.id.desc()).first())
            if row is not None:
                row.message_text, row.token_number = text, token
                if checkin is not None:
                    row.checkin_id = checkin.id
                if row.status == "scheduled":
                    row.status, row.status_changed_at = "pending", now
                if row.due_at > now:
                    row.due_at = now
            elif not db.query(WhatsappMessage).filter(
                    WhatsappMessage.appointment_id == appt.id, WhatsappMessage.template_key == wa.T_VISIT_TOKEN,
                    WhatsappMessage.status == "sent").first():
                wa.enqueue_message(
                    db, template_key=wa.T_VISIT_TOKEN, text=text, token_number=token,
                    checkin_id=checkin.id if checkin else None,
                    expires_at=_expiry(appt.requested_time, now, TOKEN_VALID_AFTER),
                    **_common(appt, account, patient, name, created_by))
        _finish(db, commit)
        return True
    except Exception:
        logger.exception("Could not release the token message")
        _undo_partial(db, commit)
        return False


def refresh_due_token_messages(db: Session, now) -> int:
    """Scheduler step, just before scheduled messages become due: rebuilds the text of every token message that
    is about to become due, so the room and token are the real ones at that moment. The caller commits."""
    rows = (db.query(WhatsappMessage)
            .filter(WhatsappMessage.template_key == wa.T_VISIT_TOKEN, WhatsappMessage.status == "scheduled",
                    WhatsappMessage.due_at <= now, WhatsappMessage.appointment_id.isnot(None),
                    WhatsappMessage.is_sample == False)  # noqa: E712
            .all())
    done = 0
    for row in rows:
        try:
            with db.begin_nested():
                appt = db.query(Appointment).filter(Appointment.id == row.appointment_id).first()
                if appt is None:
                    continue
                hospital, doctor, account, patient, name = _context(db, appt)
                token, checkin = _token_for(db, appt, hospital)
                row.message_text = _token_text(db, appt, hospital, doctor, patient, name, token, checkin)
                row.token_number = token
                if checkin is not None:
                    row.checkin_id = checkin.id
                done += 1
        except Exception:
            logger.exception("Could not refresh token message %s", row.id)
    return done