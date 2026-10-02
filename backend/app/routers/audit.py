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

LOGGED_ACTIONS = [
    "account_created", "account_activated", "account_deactivated", "account_updated",
    "role_changed",
    "patient_created", "patient_updated", "patient_checked_in",
    "vitals_recorded", "post_consult_task_completed",
    "prescription_confirmed", "consultation_voided",
    "payment_collected", "payment_reverted",
    "test_fee_paid", "test_fees_collected", "test_fees_collected_anyday",
    "medicine_created", "medicine_updated", "medicine_deactivated",
    "medicine_stock_added", "medicine_fees_collected",
    "emergency_intake", "emergency_admission",
    "test_result_saved", "test_result_edited_after_completion",
]  # kept for reference only - the audit screen now shows EVERY hospital-scoped action

# Category filter: action-name patterns (SQL LIKE). Super-admin actions stay hidden.
CATEGORY_PATTERNS = {
    "accounts": ["account_%", "role_%", "password_%", "staff_%"],
    "patients": ["patient_%", "emergency_%"],
    "clinical": ["vitals_%", "prescription_%", "consultation_%", "post_consult_%", "test_result_%",
                 "sample_%", "critical_%", "schedule_x_%", "allergy_%", "mlc_%", "consent_%", "opd_charge%"],
    "money": ["payment_%", "%_payment_%", "test_fee%", "medicine_fees%", "%fees_collected%",
              "refund_%", "waiver_%", "invoice_%", "day_end%"],
    "pharmacy": ["medicine_%", "batch_%", "stock_%", "pharmacy_%"],
    "settings": ["hospital_%", "fee_settings%", "waiver_settings%"],
}

@router.get("/logs")
def get_audit_logs(
    page: int = 1,
    limit: int = 50,
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    actor_id: Optional[int] = None,
    category: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    page = max(1, page)
    limit = min(max(1, limit), 200)

    query = db.query(AuditLog).filter(
        AuditLog.hospital_id == current_doctor.hospital_id,
        AuditLog.actor_role != "super_admin"
    )

    if category:
        from sqlalchemy import or_ as _or
        pats = CATEGORY_PATTERNS.get(category)
        if not pats:
            raise HTTPException(status_code=400, detail="Unknown category")
        query = query.filter(_or(*[AuditLog.action.like(p) for p in pats]))

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

@router.get("/export")
def export_audit_logs(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    import csv, io
    from fastapi.responses import Response
    from sqlalchemy import or_ as _or
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    q = db.query(AuditLog).filter(
        AuditLog.hospital_id == current_doctor.hospital_id,
        AuditLog.actor_role != "super_admin"
    )
    if category:
        pats = CATEGORY_PATTERNS.get(category)
        if not pats:
            raise HTTPException(status_code=400, detail="Unknown category")
        q = q.filter(_or(*[AuditLog.action.like(p) for p in pats]))
    try:
        if from_date:
            q = q.filter(AuditLog.created_at >= datetime.strptime(from_date, "%Y-%m-%d"))
        if to_date:
            q = q.filter(AuditLog.created_at <= datetime.strptime(to_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59))
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["When", "Who", "Role", "Action", "Target", "Details"])
    for l in q.order_by(desc(AuditLog.created_at)).limit(20000).all():
        row = [l.created_at.isoformat(sep=" ", timespec="seconds"), l.actor_name, l.actor_role, l.action, l.target_label, l.details or ""]
        w.writerow([("'" + c) if isinstance(c, str) and c[:1] in ("=", "+", "-", "@") else c for c in row])
    return Response(
        content="\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit-log.csv"'},
    )


@router.get("/summary")
def get_audit_summary(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    from sqlalchemy import func as _func
    query = db.query(AuditLog).filter(
        AuditLog.hospital_id == current_doctor.hospital_id,
        AuditLog.actor_role != "super_admin"
    )

    total = query.count()
    recent = query.order_by(desc(AuditLog.created_at)).limit(5).all()

    action_counts = {
        a: n for a, n in db.query(AuditLog.action, _func.count(AuditLog.id)).filter(
            AuditLog.hospital_id == current_doctor.hospital_id,
            AuditLog.actor_role != "super_admin"
        ).group_by(AuditLog.action).all()
    }

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