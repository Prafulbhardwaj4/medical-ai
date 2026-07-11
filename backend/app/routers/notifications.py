from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.doctor import Doctor
from app.models.notification import Notification
from app.utils.auth import get_current_doctor
from app.utils.notify import sync_stock_notifications

router = APIRouter(prefix="/notifications", tags=["notifications"])


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

    notifications = db.query(Notification).filter(
        Notification.hospital_id == current_doctor.hospital_id
    ).order_by(Notification.is_read.asc(), Notification.updated_at.desc()).limit(100).all()

    unread_count = db.query(Notification).filter(
        Notification.hospital_id == current_doctor.hospital_id,
        Notification.is_read == False
    ).count()

    return {"notifications": [serialize(n) for n in notifications], "unread_count": unread_count}


@router.get("/unread-count")
def get_unread_count(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin", "pharmacy"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    sync_stock_notifications(db, current_doctor.hospital_id)

    count = db.query(Notification).filter(
        Notification.hospital_id == current_doctor.hospital_id,
        Notification.is_read == False
    ).count()
    return {"unread_count": count}


@router.patch("/{notification_id}/read")
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    n = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.hospital_id == current_doctor.hospital_id
    ).first()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    n.is_read = True
    db.commit()
    return {"id": n.id, "is_read": True}


@router.post("/mark-all-read")
def mark_all_read(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    db.query(Notification).filter(
        Notification.hospital_id == current_doctor.hospital_id,
        Notification.is_read == False
    ).update({"is_read": True})
    db.commit()
    return {"marked": True}