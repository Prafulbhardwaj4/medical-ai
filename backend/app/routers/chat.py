import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.doctor import Doctor, UserRole
from app.models.chat_message import ChatMessage
from app.utils.auth import get_current_doctor
from app.utils.timezone import now_ist_naive

router = APIRouter(prefix="/chat", tags=["chat"])

ADMIN_ROLES = ["admin", "sub_admin"]
STAFF_ROLES = ["doctor", "receptionist", "nurse", "assistant", "lab", "pharmacy", "radiology"]

CHAT_UPLOAD_DIR = "chat_uploads"
os.makedirs(CHAT_UPLOAD_DIR, exist_ok=True)
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10MB
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf", ".doc", ".docx"}


def _serialize(m: ChatMessage, current_doctor: Doctor):
    return {
        "id": m.id,
        "body": m.body,
        "sender_id": m.sender_id,
        "is_mine": m.sender_id == current_doctor.id,
        "is_from_admin": m.recipient_id is None and m.sender_id != m.staff_id,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "attachment_url": f"/chat/files/{m.attachment_filename}" if m.attachment_filename else None,
        "attachment_name": m.attachment_name,
        "attachment_type": m.attachment_type,
    }


def _hospital_scope(current_doctor: Doctor, hospital_id: int | None):
    return current_doctor.hospital_id


@router.post("/upload")
def upload_chat_attachment(
    file: UploadFile = File(...),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ADMIN_ROLES + STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")

    original_name = file.filename or "attachment"
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported file type — images, PDF, or Word documents only")

    content = file.file.read()
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=400, detail="File is too large (10MB max)")

    stored_filename = f"{uuid.uuid4().hex}{ext}"
    with open(os.path.join(CHAT_UPLOAD_DIR, stored_filename), "wb") as f:
        f.write(content)

    return {
        "attachment_filename": stored_filename,
        "attachment_name": original_name,
        "attachment_type": "image" if ext in IMAGE_EXTENSIONS else "file",
    }


@router.get("/files/{filename}")
def get_chat_attachment(
    filename: str,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    # Only someone in the same hospital as the message this file belongs to can fetch it.
    msg = db.query(ChatMessage).filter(ChatMessage.attachment_filename == filename).first()
    if not msg or msg.hospital_id != current_doctor.hospital_id:
        raise HTTPException(status_code=404, detail="File not found")
    path = os.path.join(CHAT_UPLOAD_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=msg.attachment_name or filename)


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
        Doctor.role.in_([UserRole.doctor, UserRole.receptionist, UserRole.nurse, UserRole.assistant, UserRole.lab, UserRole.pharmacy, UserRole.radiology])
    ).all()

    result = []
    for s in staff:
        last = db.query(ChatMessage).filter(
            ChatMessage.staff_id == s.id,
            ChatMessage.recipient_id.is_(None)
        ).order_by(ChatMessage.created_at.desc()).first()
        unread = db.query(ChatMessage).filter(
            ChatMessage.staff_id == s.id,
            ChatMessage.recipient_id.is_(None),
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

    msgs = db.query(ChatMessage).filter(
        ChatMessage.staff_id == staff_id,
        ChatMessage.recipient_id.is_(None)
    ).order_by(ChatMessage.created_at.asc()).all()
    db.query(ChatMessage).filter(
        ChatMessage.staff_id == staff_id,
        ChatMessage.recipient_id.is_(None),
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
    attachment_filename = payload.get("attachment_filename")
    if not body and not attachment_filename:
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
        attachment_filename=attachment_filename,
        attachment_name=payload.get("attachment_name"),
        attachment_type=payload.get("attachment_type"),
        is_read_by_admin=True,
        is_read_by_staff=False,
        created_at=now_ist_naive()
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return _serialize(m, current_doctor)


@router.post("/broadcast")
def broadcast_to_all_staff(
    payload: dict,
    hospital_id: int | None = Query(None),
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Sends the same message into every staff member's own admin thread —
    each staff member sees it as a normal message from admin in their
    existing chat, not a separate broadcast inbox."""
    if current_doctor.role.value not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")

    body = (payload.get("message") or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    scoped_hospital_id = _hospital_scope(current_doctor, hospital_id)
    staff = db.query(Doctor).filter(
        Doctor.hospital_id == scoped_hospital_id,
        Doctor.role.in_([UserRole.doctor, UserRole.receptionist, UserRole.nurse, UserRole.assistant, UserRole.lab, UserRole.pharmacy, UserRole.radiology])
    ).all()

    now = now_ist_naive()
    for s in staff:
        db.add(ChatMessage(
            hospital_id=s.hospital_id,
            staff_id=s.id,
            sender_id=current_doctor.id,
            body=body,
            is_read_by_admin=True,
            is_read_by_staff=False,
            created_at=now,
        ))
    db.commit()
    return {"message": f"Sent to {len(staff)} staff member(s)"}


@router.get("/messages")
def get_my_thread(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")

    msgs = db.query(ChatMessage).filter(
        ChatMessage.staff_id == current_doctor.id,
        ChatMessage.recipient_id.is_(None)
    ).order_by(ChatMessage.created_at.asc()).all()
    db.query(ChatMessage).filter(
        ChatMessage.staff_id == current_doctor.id,
        ChatMessage.recipient_id.is_(None),
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
    attachment_filename = payload.get("attachment_filename")
    if not body and not attachment_filename:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    m = ChatMessage(
        hospital_id=current_doctor.hospital_id,
        staff_id=current_doctor.id,
        sender_id=current_doctor.id,
        body=body,
        attachment_filename=attachment_filename,
        attachment_name=payload.get("attachment_name"),
        attachment_type=payload.get("attachment_type"),
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
            ChatMessage.recipient_id.is_(None),
            ChatMessage.is_read_by_staff == False
        ).count()
    elif current_doctor.role.value in ADMIN_ROLES:
        count = db.query(ChatMessage).filter(
            ChatMessage.is_read_by_admin == False,
            ChatMessage.recipient_id.is_(None),
            ChatMessage.hospital_id == current_doctor.hospital_id
        ).count()
    else:
        count = 0
    return {"unread_count": count}