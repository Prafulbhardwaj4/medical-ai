from datetime import timedelta
from sqlalchemy.orm import Session

from app.utils.timezone import now_ist_naive


def detect_no_shows(db: Session, hospital_id: int) -> None:
    """No background scheduler in this codebase — same lazy-sweep pattern
    used elsewhere. Flags today's confirmed, paid appointments that haven't
    been consulted PORTAL_NO_SHOW_THRESHOLD_MINUTES past their slot time,
    surfacing the portal MCQ (see needs_no_show_response on AppointmentOut).
    A paid no-show is NEVER cancelled or forfeited automatically: it stays
    "confirmed" until reception chooses Rebook or Refund (see /no-shows in
    portal_appointments_staff.py)."""
    from app.config import settings
    from app.models.portal import Appointment, AppointmentStatus
    from app.models.checkin import Checkin

    threshold = now_ist_naive() - timedelta(minutes=settings.PORTAL_NO_SHOW_THRESHOLD_MINUTES)

    candidates = db.query(Appointment).filter(
        Appointment.hospital_id == hospital_id,
        Appointment.status == AppointmentStatus.confirmed,
        Appointment.payment_status == "paid",
        Appointment.no_show_detected_at.is_(None),
        Appointment.requested_time <= threshold,
    ).all()

    for appt in candidates:
        checkin = db.query(Checkin).filter(Checkin.portal_appointment_id == appt.id).first()
        if checkin and checkin.is_finalized:
            continue  # actually consulted — not a no-show
        appt.no_show_detected_at = now_ist_naive()
        
    db.commit()