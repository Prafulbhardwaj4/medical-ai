from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.doctor import Doctor
from app.models.notification import Notification
from app.utils.auth import get_current_doctor
from app.utils.notify import sync_stock_notifications, sync_room_classification_notifications

router = APIRouter(prefix="/notifications", tags=["notifications"])

PHARMACY_VISIBLE_TYPES = ["low_stock", "expiring_stock"]


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
    if current_doctor.role.value not in ["admin", "sub_admin", "pharmacy"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    sync_stock_notifications(db, current_doctor.hospital_id)
    sync_room_classification_notifications(db, current_doctor.hospital_id)

    query = db.query(Notification).filter(Notification.hospital_id == current_doctor.hospital_id)
    if current_doctor.role.value == "pharmacy":
        query = query.filter(Notification.type.in_(PHARMACY_VISIBLE_TYPES))
    notifications = query.order_by(Notification.is_read.asc(), Notification.updated_at.desc()).limit(100).all()

    unread_query = db.query(Notification).filter(
        Notification.hospital_id == current_doctor.hospital_id,
        Notification.is_read == False
    )
    if current_doctor.role.value == "pharmacy":
        unread_query = unread_query.filter(Notification.type.in_(PHARMACY_VISIBLE_TYPES))
    unread_count = unread_query.count()

    return {"notifications": [serialize(n) for n in notifications], "unread_count": unread_count}


@router.get("/unread-count")
def get_unread_count(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin", "pharmacy"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    sync_stock_notifications(db, current_doctor.hospital_id)
    sync_room_classification_notifications(db, current_doctor.hospital_id)

    query = db.query(Notification).filter(
        Notification.hospital_id == current_doctor.hospital_id,
        Notification.is_read == False
    )
    if current_doctor.role.value == "pharmacy":
        query = query.filter(Notification.type.in_(PHARMACY_VISIBLE_TYPES))
    count = query.count()
    return {"unread_count": count}


@router.patch("/{notification_id}/read")
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin", "pharmacy"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    n = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.hospital_id == current_doctor.hospital_id
    ).first()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    if current_doctor.role.value == "pharmacy" and n.type not in PHARMACY_VISIBLE_TYPES:
        raise HTTPException(status_code=403, detail="Not authorized")
    n.is_read = True
    db.commit()
    return {"id": n.id, "is_read": True}


@router.post("/mark-all-read")
def mark_all_read(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin", "pharmacy"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    query = db.query(Notification).filter(
        Notification.hospital_id == current_doctor.hospital_id,
        Notification.is_read == False
    )
    if current_doctor.role.value == "pharmacy":
        query = query.filter(Notification.type.in_(PHARMACY_VISIBLE_TYPES))
    query.update({"is_read": True})
    db.commit()
    return {"marked": True}