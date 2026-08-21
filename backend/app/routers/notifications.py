from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.doctor import Doctor
from app.models.notification import Notification
from app.utils.auth import get_current_doctor
from app.utils.notify import sync_stock_notifications, sync_room_classification_notifications

router = APIRouter(prefix="/notifications", tags=["notifications"])

PHARMACY_VISIBLE_TYPES = ["low_stock", "expiring_stock", "admission_medicine_order"]
RECEPTIONIST_VISIBLE_TYPES = ["new_portal_patient", "ward_change_request", "sample_rejected"]
LAB_VISIBLE_TYPES = ["admission_test_sample", "admission_sample_overdue"]
DOCTOR_VISIBLE_TYPES = ["emergency_alert", "critical_result", "no_assistant_alert", "emergency_ward_intake"]
NURSE_VISIBLE_TYPES = ["critical_result_escalation", "sample_rejected"]


def serialize(n: Notification):
    return {
        "id": n.id,
        "type": n.type,
        "severity": n.severity,
        "title": n.title,
        "message": n.message,
        "link_type": n.link_type,
        "link_id": n.link_id,
        "is_read": n.is_read,
        "created_at": n.created_at.isoformat() if n.created_at else None
    }


@router.get("")
def list_notifications(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin", "pharmacy", "receptionist", "lab", "doctor", "nurse", "assistant"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    sync_stock_notifications(db, current_doctor.hospital_id)
    sync_room_classification_notifications(db, current_doctor.hospital_id)

    query = db.query(Notification).filter(Notification.hospital_id == current_doctor.hospital_id)
    if current_doctor.role.value == "pharmacy":
        query = query.filter(Notification.type.in_(PHARMACY_VISIBLE_TYPES))
    if current_doctor.role.value == "receptionist":
        query = query.filter(Notification.type.in_(RECEPTIONIST_VISIBLE_TYPES))
    if current_doctor.role.value == "lab":
        query = query.filter(Notification.type.in_(LAB_VISIBLE_TYPES))
    if current_doctor.role.value == "doctor":
        query = query.filter(Notification.type.in_(DOCTOR_VISIBLE_TYPES), Notification.target_doctor_id == current_doctor.id)
    if current_doctor.role.value in ("nurse", "assistant"):
        query = query.filter(Notification.type.in_(NURSE_VISIBLE_TYPES))
    if current_doctor.role.value in ("admin", "sub_admin"):
        # target_doctor_id marks a notification as meant for one specific
        # individual (e.g. a staff member's suggestion reply) — admin/
        # sub_admin should only see it if they ARE that individual, not
        # every such notification hospital-wide.
        query = query.filter(
            (Notification.target_doctor_id.is_(None)) | (Notification.target_doctor_id == current_doctor.id)
        )
    notifications = query.order_by(Notification.is_read.asc(), Notification.updated_at.desc()).limit(100).all()

    unread_query = db.query(Notification).filter(
        Notification.hospital_id == current_doctor.hospital_id,
        Notification.is_read == False
    )
    if current_doctor.role.value == "pharmacy":
        unread_query = unread_query.filter(Notification.type.in_(PHARMACY_VISIBLE_TYPES))
    if current_doctor.role.value == "receptionist":
        unread_query = unread_query.filter(Notification.type.in_(RECEPTIONIST_VISIBLE_TYPES))
    if current_doctor.role.value == "lab":
        unread_query = unread_query.filter(Notification.type.in_(LAB_VISIBLE_TYPES))
    if current_doctor.role.value == "doctor":
        unread_query = unread_query.filter(Notification.type.in_(DOCTOR_VISIBLE_TYPES), Notification.target_doctor_id == current_doctor.id)
    if current_doctor.role.value in ("nurse", "assistant"):
        unread_query = unread_query.filter(Notification.type.in_(NURSE_VISIBLE_TYPES))
    if current_doctor.role.value in ("admin", "sub_admin"):
        unread_query = unread_query.filter(
            (Notification.target_doctor_id.is_(None)) | (Notification.target_doctor_id == current_doctor.id)
        )
    unread_count = unread_query.count()

    return {"notifications": [serialize(n) for n in notifications], "unread_count": unread_count}


@router.get("/unread-count")
def get_unread_count(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin", "pharmacy", "receptionist", "lab", "doctor", "nurse", "assistant"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    sync_stock_notifications(db, current_doctor.hospital_id)
    sync_room_classification_notifications(db, current_doctor.hospital_id)

    query = db.query(Notification).filter(
        Notification.hospital_id == current_doctor.hospital_id,
        Notification.is_read == False
    )
    if current_doctor.role.value == "pharmacy":
        query = query.filter(Notification.type.in_(PHARMACY_VISIBLE_TYPES))
    if current_doctor.role.value == "receptionist":
        query = query.filter(Notification.type.in_(RECEPTIONIST_VISIBLE_TYPES))
    if current_doctor.role.value == "lab":
        query = query.filter(Notification.type.in_(LAB_VISIBLE_TYPES))
    if current_doctor.role.value == "doctor":
        query = query.filter(Notification.type.in_(DOCTOR_VISIBLE_TYPES), Notification.target_doctor_id == current_doctor.id)
    if current_doctor.role.value in ("nurse", "assistant"):
        query = query.filter(Notification.type.in_(NURSE_VISIBLE_TYPES))
    if current_doctor.role.value in ("admin", "sub_admin"):
        query = query.filter(
            (Notification.target_doctor_id.is_(None)) | (Notification.target_doctor_id == current_doctor.id)
        )
    count = query.count()
    return {"unread_count": count}


@router.patch("/{notification_id}/read")
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin", "pharmacy", "receptionist", "lab", "doctor", "nurse", "assistant"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    n = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.hospital_id == current_doctor.hospital_id
    ).first()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    if current_doctor.role.value == "pharmacy" and n.type not in PHARMACY_VISIBLE_TYPES:
        raise HTTPException(status_code=403, detail="Not authorized")
    if current_doctor.role.value == "receptionist" and n.type not in RECEPTIONIST_VISIBLE_TYPES:
        raise HTTPException(status_code=403, detail="Not authorized")
    if current_doctor.role.value == "doctor" and (n.type not in DOCTOR_VISIBLE_TYPES or n.target_doctor_id != current_doctor.id):
        raise HTTPException(status_code=403, detail="Not authorized")
    if current_doctor.role.value == "lab" and n.type not in LAB_VISIBLE_TYPES:
        raise HTTPException(status_code=403, detail="Not authorized")
    if current_doctor.role.value in ("nurse", "assistant") and n.type not in NURSE_VISIBLE_TYPES:
        raise HTTPException(status_code=403, detail="Not authorized")
    n.is_read = True
    db.commit()
    return {"id": n.id, "is_read": True}


@router.post("/mark-all-read")
def mark_all_read(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin", "pharmacy", "receptionist", "lab"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    query = db.query(Notification).filter(
        Notification.hospital_id == current_doctor.hospital_id,
        Notification.is_read == False
    )
    if current_doctor.role.value == "pharmacy":
        query = query.filter(Notification.type.in_(PHARMACY_VISIBLE_TYPES))
    if current_doctor.role.value == "receptionist":
        query = query.filter(Notification.type.in_(RECEPTIONIST_VISIBLE_TYPES))
    if current_doctor.role.value == "lab":
        query = query.filter(Notification.type.in_(LAB_VISIBLE_TYPES))
    if current_doctor.role.value in ("admin", "sub_admin"):
        query = query.filter(
            (Notification.target_doctor_id.is_(None)) | (Notification.target_doctor_id == current_doctor.id)
        )
    query.update({"is_read": True})
    db.commit()
    return {"marked": True}