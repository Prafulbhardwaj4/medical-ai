import os
import uuid

import re as _re
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from app.utils.route_limits import per_ip_limit
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.doctor import Doctor, UserRole
from app.models.chat_message import ChatMessage
from app.services import storage
from app.utils.auth import get_current_doctor
from app.utils.tier_gate import require_tier
from app.utils.timezone import now_ist_naive

# Growth+ only, for every chat endpoint (threads, messages, broadcast, uploads, files).
router = APIRouter(
    prefix="/chat",
    tags=["chat"],
    dependencies=[Depends(require_tier("growth", "Staff chat"))],
)

ADMIN_ROLES = ["admin", "sub_admin"]
STAFF_ROLES = ["doctor", "receptionist", "nurse", "assistant", "lab", "pharmacy", "radiology"]

CHAT_UPLOAD_DIR = os.environ.get("CHAT_UPLOAD_DIR", "chat_uploads")
os.makedirs(CHAT_UPLOAD_DIR, exist_ok=True)
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10MB
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf", ".doc", ".docx"}
_READ_CHUNK_BYTES = 64 * 1024


def _read_capped(upload_file, cap: int = MAX_ATTACHMENT_BYTES) -> bytes:
    """Reads the upload in small chunks and stops as soon as it goes over the cap, so an oversized
    file is never fully loaded into memory."""
    buf = bytearray()
    while True:
        chunk = upload_file.file.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > cap:
            raise HTTPException(status_code=400, detail="File is too large (10MB max)")
    return bytes(buf)


def _signature_matches(ext: str, content: bytes) -> bool:
    """True when the real file bytes match the extension the user gave (the name alone proves nothing)."""
    if ext in (".jpg", ".jpeg"):
        return content[:3] == b"\xff\xd8\xff"
    if ext == ".png":
        return content[:8] == b"\x89PNG\r\n\x1a\n"
    if ext == ".gif":
        return content[:6] in (b"GIF87a", b"GIF89a")
    if ext == ".webp":
        return content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    if ext == ".pdf":
        return b"%PDF-" in content[:1024]
    if ext == ".doc":
        return content[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    if ext == ".docx":
        if content[:4] != b"PK\x03\x04":
            return False
        try:
            import io
            import zipfile
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                names = z.namelist()
            return "[Content_Types].xml" in names and any(n.startswith("word/") for n in names)
        except Exception:
            return False
    return False


def scan_upload(path: str) -> None:
    """MALWARE SCANNER HOOK. Called with the path of every saved chat upload, before the upload is accepted.
    Default: does nothing. To plug in a scanner (for example ClamAV), run it here on `path` and raise
    ValueError if the file is infected; the upload is then deleted and refused."""
    return None


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
    current_doctor: Doctor = Depends(get_current_doctor),
    _limit: None = Depends(per_ip_limit("chat_upload", "30/minute", "300/hour")),
):
    if current_doctor.role.value not in ADMIN_ROLES + STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")

    original_name = file.filename or "attachment"
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported file type — images, PDF, or Word documents only")

    content = _read_capped(file)
    if not content:
        raise HTTPException(status_code=400, detail="The file is empty")
    if not _signature_matches(ext, content):
        raise HTTPException(status_code=400, detail="This file does not look like a real " + ext.lstrip(".").upper() + " file")

    stored_filename = f"{uuid.uuid4().hex}{ext}"
    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=ext)
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(content)
        scan_upload(tmp_path)
    except Exception:
        raise HTTPException(status_code=400, detail="This file could not be accepted")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
    storage.save_chat_file(stored_filename, content)

    return {
        "attachment_filename": stored_filename,
        "attachment_name": original_name,
        "attachment_type": "image" if ext in IMAGE_EXTENSIONS else "file",
    }


_ATTACH_FILE_RE = _re.compile(r"^[0-9a-f]{32}\.[a-z0-9]{2,5}$")


def _clean_attachment(payload: dict):
    fn = payload.get("attachment_filename")
    if not fn:
        return None, None, None
    if not isinstance(fn, str) or not _ATTACH_FILE_RE.match(fn):
        raise HTTPException(status_code=400, detail="Invalid attachment")
    name = str(payload.get("attachment_name") or "file")[:150]
    atype = "image" if payload.get("attachment_type") == "image" else "file"
    return fn, name, atype


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
    data = storage.read_chat_file(filename)
    if data is None:
        raise HTTPException(status_code=404, detail="File not found")
    import mimetypes
    from urllib.parse import quote
    name = (msg.attachment_name or filename)
    safe = name.replace('"', "_").replace("\\", "_").replace("\r", "_").replace("\n", "_")
    try:
        safe.encode("ascii")
        disposition = f'attachment; filename="{safe}"'
    except UnicodeEncodeError:
        disposition = "attachment; filename*=utf-8''" + quote(safe)
    return Response(content=data, media_type=mimetypes.guess_type(safe)[0] or "application/octet-stream",
                    headers={"Content-Disposition": disposition, "X-Content-Type-Options": "nosniff"})


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
    _att = _clean_attachment(payload)
    attachment_filename = _att[0]
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
        attachment_filename=_att[0],
        attachment_name=_att[1],
        attachment_type=_att[2],
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
    _att = _clean_attachment(payload)
    attachment_filename = _att[0]
    if not body and not attachment_filename:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    m = ChatMessage(
        hospital_id=current_doctor.hospital_id,
        staff_id=current_doctor.id,
        sender_id=current_doctor.id,
        body=body,
        attachment_filename=_att[0],
        attachment_name=_att[1],
        attachment_type=_att[2],
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