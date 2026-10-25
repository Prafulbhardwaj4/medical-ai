from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import or_, and_, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.doctor import Doctor
from app.models.hospital import Hospital
from app.models.whatsapp_message import WhatsappMessage
from app.services import whatsapp_messages as wa
from app.utils.audit import log_action
from app.utils.rate_limit import limiter
from app.utils.roles import require_roles
from app.utils.timezone import now_ist_naive

router = APIRouter(prefix="/whatsapp-messages", tags=["whatsapp-messages"])

_staff = require_roles("super_admin", "admin", "receptionist")
_super = require_roles("super_admin")

STATUS_FILTERS = {"all", "due", "pending", "scheduled", "sent", "expired", "cancelled"}


# ---------------------------------------------------------------------------
# Scope: hospital + role visibility, enforced in the query itself
# ---------------------------------------------------------------------------
def _scoped(db: Session, user: Doctor):
    role = user.role.value
    q = db.query(WhatsappMessage).filter(WhatsappMessage.visibility.in_(wa.VISIBLE_LEVELS_FOR_ROLE[role]))
    if role != "super_admin":
        if user.hospital_id is None:
            return q.filter(WhatsappMessage.id == -1)
        q = q.filter(WhatsappMessage.hospital_id == user.hospital_id, WhatsappMessage.is_sample == False)  # noqa: E712
    return q


def _get_visible(db: Session, user: Doctor, message_id: int) -> WhatsappMessage:
    row = _scoped(db, user).filter(WhatsappMessage.id == message_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return row


def _effective_status(row: WhatsappMessage, now) -> str:
    if row.status == "scheduled" and row.due_at <= now:
        return "due"
    return row.status


def _serialize(row: WhatsappMessage, hospital_name, marker_name, now) -> dict:
    status = _effective_status(row, now)
    if row.is_secret:
        text = row.message_text if row.secret_enc else wa.EXPIRED_TEXT
    else:
        text = row.message_text
    can_undo = bool(
        row.prev_status and row.status in ("sent", "cancelled") and not row.is_sample
        and (not row.is_secret or row.secret_enc)
    )
    return {
        "id": row.id,
        "hospital_id": row.hospital_id,
        "hospital_name": hospital_name,
        "recipient_name": row.recipient_name,
        "recipient_role": row.recipient_role,
        "recipient_phone": row.recipient_phone,
        "template_key": row.template_key,
        "type_label": wa.TYPE_LABELS.get(row.template_key, row.template_key),
        "text": text,
        "is_secret": row.is_secret,
        "secret_available": bool(row.is_secret and row.secret_enc and status in wa.OPEN_STATUSES),
        "status": status,
        "due_at": row.due_at.isoformat() if row.due_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "is_sample": row.is_sample,
        "sent_marked_at": row.sent_marked_at.isoformat() if row.sent_marked_at else None,
        "sent_marked_by_name": marker_name,
        "can_mark_sent": (not row.is_sample) and status in ("due", "pending"),
        "can_cancel": (not row.is_sample) and status in wa.OPEN_STATUSES,
        "can_undo": can_undo,
    }


def _serialize_one(db: Session, row: WhatsappMessage) -> dict:
    hospital = db.query(Hospital.name).filter(Hospital.id == row.hospital_id).first() if row.hospital_id else None
    marker = db.query(Doctor.title, Doctor.name).filter(Doctor.id == row.sent_marked_by).first() if row.sent_marked_by else None
    marker_name = f"{marker[0] or ''} {marker[1]}".strip() if marker else None
    return _serialize(row, hospital[0] if hospital else None, marker_name, now_ist_naive())


def _label(row: WhatsappMessage) -> str:
    return f"{wa.TYPE_LABELS.get(row.template_key, row.template_key)} to {row.recipient_name}"[:200]


def _due_or_pending_filter(now):
    return or_(
        WhatsappMessage.status.in_(("due", "pending")),
        and_(WhatsappMessage.status == "scheduled", WhatsappMessage.due_at <= now),
    )


# ---------------------------------------------------------------------------
# List + badge
# ---------------------------------------------------------------------------
@router.get("")
@limiter.limit("120/minute")
def list_messages(
    request: Request,
    status: str = "all",
    q: str = "",
    older: bool = False,
    page: int = 1,
    page_size: int = 20,
    hospital_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(_staff),
):
    if status not in STATUS_FILTERS:
        raise HTTPException(status_code=400, detail="Unknown status filter")
    page = max(1, page)
    page_size = min(max(1, page_size), 50)
    now = now_ist_naive()

    query = _scoped(db, current_doctor)
    if hospital_id is not None and current_doctor.role.value == "super_admin":
        query = query.filter(WhatsappMessage.hospital_id == hospital_id)
    if not older:
        query = query.filter(WhatsappMessage.created_at >= now - timedelta(days=7))

    if status == "due":
        query = query.filter(or_(WhatsappMessage.status == "due",
                                 and_(WhatsappMessage.status == "scheduled", WhatsappMessage.due_at <= now)))
    elif status == "scheduled":
        query = query.filter(WhatsappMessage.status == "scheduled", WhatsappMessage.due_at > now)
    elif status != "all":
        query = query.filter(WhatsappMessage.status == status)

    term = (q or "").strip()[:60]
    if term:
        like = f"%{term.replace('%', '').replace('_', '')}%"
        digits = "".join(c for c in term if c.isdigit())
        conds = [func.lower(WhatsappMessage.recipient_name).like(like.lower())]
        if len(digits) >= 3:
            conds.append(WhatsappMessage.recipient_phone.like(f"%{digits}%"))
        query = query.filter(or_(*conds))

    total = query.count()
    rows = (query.order_by(WhatsappMessage.created_at.desc(), WhatsappMessage.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())

    hospital_ids = {r.hospital_id for r in rows if r.hospital_id}
    names = {h.id: h.name for h in db.query(Hospital.id, Hospital.name).filter(Hospital.id.in_(hospital_ids)).all()} if hospital_ids else {}
    marker_ids = {r.sent_marked_by for r in rows if r.sent_marked_by}
    markers = {d.id: f"{d.title or ''} {d.name}".strip() for d in db.query(Doctor.id, Doctor.title, Doctor.name).filter(Doctor.id.in_(marker_ids)).all()} if marker_ids else {}

    return {
        "items": [_serialize(r, names.get(r.hospital_id), markers.get(r.sent_marked_by), now) for r in rows],
        "total": total, "page": page, "page_size": page_size,
        "has_more": page * page_size < total,
    }


@router.get("/badge")
@limiter.limit("120/minute")
def badge_count(request: Request, db: Session = Depends(get_db), current_doctor: Doctor = Depends(_staff)):
    now = now_ist_naive()
    count = (_scoped(db, current_doctor)
             .filter(WhatsappMessage.is_sample == False)  # noqa: E712
             .filter(_due_or_pending_filter(now)).count())
    return {"count": count}


# ---------------------------------------------------------------------------
# Single-message actions
# ---------------------------------------------------------------------------
@router.post("/{message_id}/reveal")
@limiter.limit("60/minute")
def reveal_secret(message_id: int, request: Request, db: Session = Depends(get_db), current_doctor: Doctor = Depends(_staff)):
    row = _get_visible(db, current_doctor, message_id)  # role + hospital checked again, on every call
    if not row.is_secret:
        raise HTTPException(status_code=400, detail="This message has no hidden part")
    if _effective_status(row, now_ist_naive()) not in wa.OPEN_STATUSES:
        raise HTTPException(status_code=409, detail="This message is no longer available")
    text = wa.decrypt_secret_text(row)
    if text is None:
        raise HTTPException(status_code=410, detail="This message has expired")
    log_action(db, current_doctor, action="whatsapp_secret_viewed", target_type="whatsapp_message",
               target_id=row.id, target_label=_label(row), details="Viewed the hidden part of a message",
               hospital_id=row.hospital_id)
    return {"id": row.id, "text": text}


@router.post("/{message_id}/mark-sent")
@limiter.limit("60/minute")
def mark_sent(message_id: int, request: Request, db: Session = Depends(get_db), current_doctor: Doctor = Depends(_staff)):
    row = _get_visible(db, current_doctor, message_id)
    if row.is_sample:
        raise HTTPException(status_code=400, detail="Sample messages cannot be sent")
    if _effective_status(row, now_ist_naive()) not in ("due", "pending"):
        raise HTTPException(status_code=409, detail="This message is not ready to be marked as sent")
    now = now_ist_naive()
    row.prev_status, row.status, row.status_changed_at = row.status, "sent", now
    row.sent_marked_by, row.sent_marked_at = current_doctor.id, now
    db.commit()
    log_action(db, current_doctor, action="whatsapp_message_marked_sent", target_type="whatsapp_message",
               target_id=row.id, target_label=_label(row), hospital_id=row.hospital_id)
    return _serialize_one(db, row)


@router.post("/{message_id}/cancel")
@limiter.limit("60/minute")
def cancel_message(message_id: int, request: Request, db: Session = Depends(get_db), current_doctor: Doctor = Depends(_staff)):
    row = _get_visible(db, current_doctor, message_id)
    if row.is_sample:
        raise HTTPException(status_code=400, detail="Sample messages cannot be cancelled")
    if row.status not in wa.OPEN_STATUSES:
        raise HTTPException(status_code=409, detail="This message can no longer be cancelled")
    now = now_ist_naive()
    row.prev_status, row.status, row.status_changed_at = row.status, "cancelled", now
    db.commit()
    log_action(db, current_doctor, action="whatsapp_message_cancelled", target_type="whatsapp_message",
               target_id=row.id, target_label=_label(row), hospital_id=row.hospital_id)
    return _serialize_one(db, row)


@router.post("/{message_id}/undo")
@limiter.limit("60/minute")
def undo_message(message_id: int, request: Request, db: Session = Depends(get_db), current_doctor: Doctor = Depends(_staff)):
    row = _get_visible(db, current_doctor, message_id)
    if row.is_sample or row.status not in ("sent", "cancelled") or not row.prev_status:
        raise HTTPException(status_code=409, detail="Nothing to undo")
    if row.is_secret and not row.secret_enc:
        raise HTTPException(status_code=409, detail="This message has expired and cannot be restored")
    undone = row.status
    row.status, row.prev_status = row.prev_status, None
    row.status_changed_at = now_ist_naive()
    row.sent_marked_by, row.sent_marked_at = None, None
    db.commit()
    log_action(db, current_doctor, action="whatsapp_message_undo", target_type="whatsapp_message",
               target_id=row.id, target_label=_label(row), details=f"Undid '{undone}'", hospital_id=row.hospital_id)
    return _serialize_one(db, row)


# ---------------------------------------------------------------------------
# Samples (super admin only): made-up messages to review every template. Never counted, never sent.
# ---------------------------------------------------------------------------
class SampleIn(BaseModel):
    hospital_id: Optional[int] = None


@router.post("/samples")
@limiter.limit("10/minute")
def create_samples(body: SampleIn, request: Request, db: Session = Depends(get_db), current_doctor: Doctor = Depends(_super)):
    hospital = db.query(Hospital).filter(Hospital.id == body.hospital_id).first() if body.hospital_id else None
    hname = hospital.name if hospital else "Demo Hospital"
    hphone = wa.hospital_mobile(hospital) if hospital and wa.hospital_mobile(hospital) != "the reception" else "+919876543210"
    hid = hospital.id if hospital else None
    now = now_ist_naive()
    appt_at = (now + timedelta(days=1)).replace(minute=30, second=0, microsecond=0)
    visit_at = now.replace(second=0, microsecond=0)
    common = dict(hospital_id=hid, recipient_kind="sample", created_by=current_doctor.id, is_sample=True)

    try:
        wa.enqueue_message(db, template_key=wa.T_WELCOME, recipient_name="Dr. Anil Verma", recipient_role="doctor",
                           recipient_phone="9876543210", visibility=wa.VIS_ALL,
                           text=wa.build_welcome(name="Dr. Anil Verma", role="doctor", hospital_name=hname, login_id="anil.verma@example.com"),
                           **common)
        full, masked = wa.build_temp_password("Ab12Cd34Ef")
        wa.enqueue_message(db, template_key=wa.T_TEMP_PASSWORD, recipient_name="Dr. Anil Verma", recipient_role="doctor",
                           recipient_phone="9876543210", visibility=wa.VIS_ADMIN_SUPER, secret=True,
                           text=full, masked_text=masked, **common)
        wa.enqueue_message(db, template_key=wa.T_VISIT_TOKEN, recipient_name="Ananya Sharma", recipient_role="patient",
                           recipient_phone="9812345678", visibility=wa.VIS_ALL, token_number="A-014",
                           text=wa.build_visit_token(patient_name="Ananya Sharma", hospital_name=hname, token_number="A-014",
                                                     doctor_name="Dr. Anil Verma", speciality="General Medicine", room="Room 3",
                                                     visit_datetime=visit_at, patient_uid="MEDS-A1B2C3", hospital_mobile_number=hphone),
                           **common)
        wa.enqueue_message(db, template_key=wa.T_APPT_CONFIRMED, recipient_name="Ananya Sharma", recipient_role="patient",
                           recipient_phone="9812345678", visibility=wa.VIS_ALL,
                           text=wa.build_appointment_confirmed(patient_name="Ananya Sharma", hospital_name=hname,
                                                               appt_datetime=appt_at, doctor_name="Dr. Anil Verma"),
                           **common)
        wa.enqueue_message(db, template_key=wa.T_APPT_REMINDER, recipient_name="Ananya Sharma", recipient_role="patient",
                           recipient_phone="9812345678", visibility=wa.VIS_ALL,
                           text=wa.build_appointment_reminder(patient_name="Ananya Sharma", hospital_name=hname,
                                                              appt_datetime=appt_at, doctor_name="Dr. Anil Verma"),
                           **common)
        wa.enqueue_message(db, template_key=wa.T_APPT_CANCELLED, recipient_name="Ananya Sharma", recipient_role="patient",
                           recipient_phone="9812345678", visibility=wa.VIS_ALL,
                           text=wa.build_appointment_cancelled(patient_name="Ananya Sharma", hospital_name=hname,
                                                               old_datetime=appt_at, doctor_name="Dr. Anil Verma",
                                                               rescheduled=True, hospital_mobile_number=hphone),
                           **common)
        full, masked = wa.build_forgot_otp("482913")
        wa.enqueue_message(db, template_key=wa.T_FORGOT_OTP, recipient_name="Ananya Sharma", recipient_role="patient",
                           recipient_phone="9812345678", visibility=wa.VIS_ADMIN_SUPER, secret=True,
                           text=full, masked_text=masked, **common)
    except wa.SecretKeyMissing:
        db.rollback()
        raise HTTPException(status_code=503, detail="WHATSAPP_MESSAGES_KEY is not set on the server")
    db.commit()
    log_action(db, current_doctor, action="whatsapp_samples_created", target_type="whatsapp_message",
               details="Created sample messages", hospital_id=hid)
    return {"created": 7}


@router.delete("/samples")
@limiter.limit("10/minute")
def clear_samples(request: Request, db: Session = Depends(get_db), current_doctor: Doctor = Depends(_super)):
    removed = db.query(WhatsappMessage).filter(WhatsappMessage.is_sample == True).delete(synchronize_session=False)  # noqa: E712
    db.commit()
    log_action(db, current_doctor, action="whatsapp_samples_cleared", target_type="whatsapp_message",
               details=f"Cleared {removed} sample message(s)")
    return {"removed": removed}