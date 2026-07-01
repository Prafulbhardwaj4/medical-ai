from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional
from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.doctor import Doctor
from app.utils.auth import get_current_doctor
from datetime import datetime

router = APIRouter(prefix="/audit", tags=["audit"])

@router.get("/logs")
def get_audit_logs(
    page: int = 1,
    limit: int = 50,
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    actor_id: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    query = db.query(AuditLog)

    # super_admin sees all, admin/sub_admin see only their hospital
    if current_doctor.role.value != "super_admin":
        query = query.filter(AuditLog.hospital_id == current_doctor.hospital_id)

    if action:
        query = query.filter(AuditLog.action == action)
    if target_type:
        query = query.filter(AuditLog.target_type == target_type)
    if actor_id:
        query = query.filter(AuditLog.actor_id == actor_id)

    if from_date:
        try:
            fd = datetime.strptime(from_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid from_date format. Use YYYY-MM-DD")
        query = query.filter(AuditLog.created_at >= fd)

    if to_date:
        try:
            td = datetime.strptime(to_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid to_date format. Use YYYY-MM-DD")
        query = query.filter(AuditLog.created_at <= td)

    total = query.count()
    logs = query.order_by(desc(AuditLog.created_at)).offset((page - 1) * limit).limit(limit).all()

    return {
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,
        "logs": [
            {
                "id": l.id,
                "actor_name": l.actor_name,
                "actor_role": l.actor_role,
                "action": l.action,
                "target_type": l.target_type,
                "target_id": l.target_id,
                "target_label": l.target_label,
                "details": l.details,
                "created_at": l.created_at.isoformat()
            }
            for l in logs
        ]
    }


@router.get("/summary")
def get_audit_summary(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    query = db.query(AuditLog)
    if current_doctor.role.value != "super_admin":
        query = query.filter(AuditLog.hospital_id == current_doctor.hospital_id)

    total = query.count()
    recent = query.order_by(desc(AuditLog.created_at)).limit(5).all()

    action_counts = {}
    for log in query.all():
        action_counts[log.action] = action_counts.get(log.action, 0) + 1

    return {
        "total_events": total,
        "action_breakdown": action_counts,
        "recent": [
            {
                "actor_name": l.actor_name,
                "action": l.action,
                "target_label": l.target_label,
                "created_at": l.created_at.isoformat()
            }
            for l in recent
        ]
    }