"""Stores Super Admin pilot notifications once each (unique dedupe key).
The event row and its audit entry are added to the CURRENT transaction; the caller commits."""
from sqlalchemy.exc import IntegrityError

from app.models.superadmin_event import SuperAdminEvent
from app.utils.audit import stage_action


def record_pilot_event(db, hospital, event_type, dedupe_key, title, message, severity="warning"):
    """Returns True if the event was newly stored, False if this dedupe key already exists."""
    if db.query(SuperAdminEvent.id).filter(SuperAdminEvent.dedupe_key == dedupe_key).first():
        return False
    try:
        with db.begin_nested():
            db.add(SuperAdminEvent(
                hospital_id=hospital.id, dedupe_key=dedupe_key, event_type=event_type,
                severity=severity, title=title, message=message,
            ))
            db.flush()
    except IntegrityError:
        return False  # another request stored the same event first
    stage_action(
        db, None, "pilot_notification_created", "hospital", hospital.id, hospital.name,
        message, hospital_id=hospital.id,
    )
    return True