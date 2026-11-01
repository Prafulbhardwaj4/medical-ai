"""Pilot lifecycle: deadline-day notification, grace period, deactivation after grace.

ONE function does all of it (ensure_pilot_lifecycle). It is called from:
  - the nightly scheduler job (00:00 IST),
  - the shared authentication dependency and the login route (request-time, so nothing is lost
    if the job did not run).
Every step is idempotent: events have a unique dedupe key and the deactivation is a conditional update.
The scribe stop during grace is enforced by the scribe gate (app/utils/ai_scribe_gate.py), not here.
"""
import logging

from app.models.hospital import Hospital
from app.utils.audit import stage_action
from app.utils.pilot import is_pilot, pilot_state
from app.utils.pilot_events import record_pilot_event
from app.utils.timezone import ist_today

logger = logging.getLogger("pilot_lifecycle")


def ensure_pilot_lifecycle(db, hospital, today=None) -> bool:
    """Brings a pilot hospital's stored state up to date for `today` (IST date).
    Returns True when the hospital must be treated as deactivated right now (pilot past its grace period).
    Non-pilot hospitals, pilots before their deadline, and pilots without dates return False and change nothing."""
    if not hospital or not is_pilot(hospital.tier):
        return False
    s = pilot_state(hospital, today or ist_today())
    if s["phase"] not in ("grace", "expired"):
        return False
    expired = s["phase"] == "expired"
    if not hospital.is_active:
        return expired  # already deactivated (by this rule or by the Super Admin): nothing more to create

    try:
        end_iso = s["end"].isoformat()
        changed = record_pilot_event(
            db, hospital, "pilot_deadline", f"pilot_deadline:{hospital.id}:{end_iso}",
            "Pilot deadline today",
            f"{hospital.name}: pilot deadline today. Grace period started (scribe stopped).",
        )
        if expired:
            # Conditional update: only the request/job that really flips the flag writes the audit entry.
            flipped = db.query(Hospital).filter(
                Hospital.id == hospital.id, Hospital.is_active == True,  # noqa: E712
            ).update({"is_active": False}, synchronize_session=False)
            if flipped:
                hospital.is_active = False
                stage_action(
                    db, None, "pilot_hospital_deactivated", "hospital", hospital.id, hospital.name,
                    f"Pilot grace period over (pilot ended {end_iso}); hospital deactivated",
                    hospital_id=hospital.id,
                )
                record_pilot_event(
                    db, hospital, "pilot_grace_over", f"pilot_grace_over:{hospital.id}:{end_iso}",
                    "Pilot grace period over",
                    f"{hospital.name}: grace period over. Hospital deactivated.",
                    severity="danger",
                )
                changed = True
        if changed:
            db.commit()
    except Exception:
        db.rollback()
        logger.exception("Pilot lifecycle update failed for hospital %s", getattr(hospital, "id", None))
    return expired


def run_pilot_lifecycle_sweep(db, today=None) -> int:
    """Nightly job body: applies ensure_pilot_lifecycle to every active pilot hospital. Returns how many were deactivated."""
    from app.utils.pilot import PILOT_TIERS

    deactivated = 0
    hospitals = db.query(Hospital).filter(
        Hospital.tier.in_(PILOT_TIERS),
        Hospital.pilot_start_date.isnot(None),
        Hospital.is_active == True,  # noqa: E712
    ).all()
    for hospital in hospitals:
        was_active = hospital.is_active
        ensure_pilot_lifecycle(db, hospital, today)
        db.refresh(hospital)
        if was_active and not hospital.is_active:
            deactivated += 1
    return deactivated