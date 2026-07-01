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
    db.add(entry)
    db.commit()