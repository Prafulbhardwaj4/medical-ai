from sqlalchemy.orm import Session
from app.models.audit_log import AuditLog


def log_action(
    db: Session,
    actor,
    action: str,
    target_type: str,
    target_id: int = None,
    target_label: str = None,
    details: str = None,
    hospital_id: int = None
):
    entry = AuditLog(
        actor_id=actor.id if actor else None,
        actor_name=f"{actor.title} {actor.name}" if actor and actor.title else (actor.name if actor else "System"),
        actor_role=actor.role.value if actor else "system",
        hospital_id=hospital_id if hospital_id is not None else (actor.hospital_id if actor else None),
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_label=target_label,
        details=details
    )
    try:
        db.add(entry)
        db.commit()
    except Exception:
        # The business change was already committed by the caller. Never fail the request
        # just because the audit row failed.
        db.rollback()
        import logging
        logging.getLogger("audit").exception("AUDIT WRITE FAILED action=%s target=%s/%s", action, target_type, target_id)


def stage_action(db: Session, actor, action: str, target_type: str, target_id: int = None,
                 target_label: str = None, details: str = None, hospital_id: int = None):
    """Adds the audit row to the CURRENT transaction without committing, so it is saved
    (or rolled back) together with the caller's own change."""
    db.add(AuditLog(
        actor_id=actor.id if actor else None,
        actor_name=f"{actor.title} {actor.name}" if actor and actor.title else (actor.name if actor else "System"),
        actor_role=actor.role.value if actor else "system",
        hospital_id=hospital_id if hospital_id is not None else (actor.hospital_id if actor else None),
        action=action, target_type=target_type, target_id=target_id,
        target_label=target_label, details=details,
    ))


def log_record_access(db: Session, actor, action: str, target_type: str, target_id: int,
                      target_label: str = None, dedupe_minutes: int = 10):
    """Who opened / downloaded patient data, and when. The same person re-opening the
    same record within `dedupe_minutes` is logged once, so the log stays readable."""
    import logging
    from datetime import timedelta
    from app.utils.timezone import now_ist_naive
    try:
        cutoff = now_ist_naive() - timedelta(minutes=dedupe_minutes)
        already = db.query(AuditLog.id).filter(
            AuditLog.actor_id == actor.id, AuditLog.action == action,
            AuditLog.target_type == target_type, AuditLog.target_id == target_id,
            AuditLog.created_at >= cutoff,
        ).first()
        if already:
            return
        stage_action(db, actor, action, target_type, target_id, target_label)
        db.commit()
    except Exception:
        db.rollback()
        logging.getLogger("audit").exception("ACCESS LOG FAILED action=%s target=%s/%s", action, target_type, target_id)