from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.doctor import Doctor, UserRole
from app.models.chat_message import ChatMessage
from app.utils.auth import get_current_doctor
from app.utils.timezone import now_ist_naive

router = APIRouter(prefix="/chat", tags=["chat"])

ADMIN_ROLES = ["admin", "sub_admin"]
STAFF_ROLES = ["doctor", "receptionist", "nurse", "lab", "pharmacy"]


def _serialize(m: ChatMessage, current_doctor: Doctor):
    return {
        "id": m.id,
        "body": m.body,
        "sender_id": m.sender_id,
        "is_mine": m.sender_id == current_doctor.id,
        "is_from_admin": m.sender_id != m.staff_id,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def _hospital_scope(current_doctor: Doctor, hospital_id: int | None):
    return current_doctor.hospital_id


@router.get("/threads")
def list_threads(
    hospital_id: int | None = Query(None),
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")

    scoped_hospital_id = _hospital_scope(current_doctor, hospital_id)

    staff = db.query(Doctor).filter(
        Doctor.hospital_id == scoped_hospital_id,
        Doctor.role.in_([UserRole.doctor, UserRole.receptionist, UserRole.nurse, UserRole.lab, UserRole.pharmacy])
    ).all()

    result = []
    for s in staff:
        last = db.query(ChatMessage).filter(ChatMessage.staff_id == s.id).order_by(ChatMessage.created_at.desc()).first()
        unread = db.query(ChatMessage).filter(
            ChatMessage.staff_id == s.id,
            ChatMessage.is_read_by_admin == False
        ).count()
        result.append({
            "staff_id": s.id,
            "name": s.name,
            "role": s.role.value,
            "last_message": last.body if last else None,
            "last_message_at": last.created_at.isoformat() if last else None,
            "unread_count": unread
        })
    result.sort(key=lambda r: r["last_message_at"] or "", reverse=True)
    return result


@router.get("/threads/{staff_id}/messages")
def get_thread_as_admin(
    staff_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")

    staff = db.query(Doctor).filter(Doctor.id == staff_id).first()
    if not staff or staff.role.value not in STAFF_ROLES:
        raise HTTPException(status_code=404, detail="Staff member not found")
    if staff.hospital_id != current_doctor.hospital_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    msgs = db.query(ChatMessage).filter(ChatMessage.staff_id == staff_id).order_by(ChatMessage.created_at.asc()).all()
    db.query(ChatMessage).filter(
        ChatMessage.staff_id == staff_id,
        ChatMessage.is_read_by_admin == False
    ).update({"is_read_by_admin": True})
    db.commit()
    return {"staff_name": staff.name, "messages": [_serialize(m, current_doctor) for m in msgs]}


@router.post("/threads/{staff_id}/messages")
def send_as_admin(
    staff_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")

    body = (payload.get("message") or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    staff = db.query(Doctor).filter(Doctor.id == staff_id).first()
    if not staff or staff.role.value not in STAFF_ROLES:
        raise HTTPException(status_code=404, detail="Staff member not found")
    if staff.hospital_id != current_doctor.hospital_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    m = ChatMessage(
        hospital_id=staff.hospital_id,
        staff_id=staff.id,
        sender_id=current_doctor.id,
        body=body,
        is_read_by_admin=True,
        is_read_by_staff=False,
        created_at=now_ist_naive()
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return _serialize(m, current_doctor)


@router.get("/messages")
def get_my_thread(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")

    msgs = db.query(ChatMessage).filter(ChatMessage.staff_id == current_doctor.id).order_by(ChatMessage.created_at.asc()).all()
    db.query(ChatMessage).filter(
        ChatMessage.staff_id == current_doctor.id,
        ChatMessage.is_read_by_staff == False
    ).update({"is_read_by_staff": True})
    db.commit()
    return {"messages": [_serialize(m, current_doctor) for m in msgs]}


@router.post("/messages")
def send_as_staff(
    payload: dict,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")

    body = (payload.get("message") or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    m = ChatMessage(
        hospital_id=current_doctor.hospital_id,
        staff_id=current_doctor.id,
        sender_id=current_doctor.id,
        body=body,
        is_read_by_admin=False,
        is_read_by_staff=True,
        created_at=now_ist_naive()
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return _serialize(m, current_doctor)


@router.get("/unread-count")
def unread_count(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value in STAFF_ROLES:
        count = db.query(ChatMessage).filter(
            ChatMessage.staff_id == current_doctor.id,
            ChatMessage.is_read_by_staff == False
        ).count()
    elif current_doctor.role.value in ADMIN_ROLES:
        count = db.query(ChatMessage).filter(
            ChatMessage.is_read_by_admin == False,
            ChatMessage.hospital_id == current_doctor.hospital_id
        ).count()
    else:
        count = 0
    return {"unread_count": count}