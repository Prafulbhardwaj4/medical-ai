"""Forgot-password codes for staff and hospital admins (super admins never use this).

Only an account that has already set its own password can ask for a code. A request makes a random
6-digit code, stores only its HMAC, and puts the WhatsApp message with the code in the messages list
(a hospital admin's code: super admin only; any other staff code: that hospital's admin and the super
admin). The code is valid 10 minutes, allows 5 tries, works once, and a new request kills the earlier
code. The readable code is never logged and never returned by any API."""
import hashlib
import hmac
import logging
import re
import secrets
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.doctor import UserRole
from app.models.staff_reset_code import StaffResetCode
from app.services import whatsapp_messages as wa
from app.utils.timezone import now_ist_naive

logger = logging.getLogger("staff_reset")

CODE_VALID_MINUTES = wa.OTP_VALID_MINUTES  # 10
MAX_ATTEMPTS = 5
MAX_CODES_PER_HOUR = 3  # per account
KEEP_USED_DAYS = 1


def hash_reset_code(doctor_id: int, code: str) -> str:
    """Keyed hash (HMAC-SHA256 with the server secret)."""
    return hmac.new(
        settings.SECRET_KEY.encode(), f"staff-reset-v1:{doctor_id}:{code}".encode(), hashlib.sha256
    ).hexdigest()


def is_eligible(doctor) -> bool:
    """Active staff or hospital admin, in an active hospital, who has already set their own password.
    A super admin never qualifies. An account that never signed in gets its code from the admin."""
    if doctor is None or not doctor.is_active or doctor.role == UserRole.super_admin:
        return False
    if doctor.must_change_password or not doctor.hospital_id:
        return False
    return bool(doctor.hospital and doctor.hospital.is_active)


def issue_staff_reset_code(db: Session, doctor) -> bool:
    """Creates a code and its list message. Returns False (and creates nothing) when the account
    already asked 3 times this hour or WHATSAPP_MESSAGES_KEY is missing. The caller gives the same
    answer either way, so nothing about the account can be learned from it."""
    now = now_ist_naive()
    recent = db.query(func.count(StaffResetCode.id)).filter(
        StaffResetCode.doctor_id == doctor.id, StaffResetCode.created_at >= now - timedelta(hours=1)
    ).scalar() or 0
    if recent >= MAX_CODES_PER_HOUR:
        return False
    code = f"{secrets.randbelow(1_000_000):06d}"  # never a fixed code
    expires = now + timedelta(minutes=CODE_VALID_MINUTES)
    visibility = wa.VIS_SUPER_ONLY if doctor.role == UserRole.admin else wa.VIS_ADMIN_SUPER
    try:
        with db.begin_nested():
            # A new request kills the earlier code and deletes its readable copy.
            wa.wipe_secrets_for_recipient(db, recipient_kind="staff", recipient_id=doctor.id,
                                          template_keys=[wa.T_FORGOT_OTP])
            db.query(StaffResetCode).filter(
                StaffResetCode.doctor_id == doctor.id, StaffResetCode.used == False  # noqa: E712
            ).update({StaffResetCode.used: True}, synchronize_session=False)
            full, masked = wa.build_forgot_otp(code)
            wa.enqueue_message(
                db, template_key=wa.T_FORGOT_OTP, text=full, masked_text=masked, secret=True,
                visibility=visibility, expires_at=expires, hospital_id=doctor.hospital_id,
                recipient_kind="staff", recipient_id=doctor.id,
                recipient_name=f"{doctor.title or ''} {doctor.name}".strip(),
                recipient_role=doctor.role.value, recipient_phone=doctor.phone,
            )
            db.add(StaffResetCode(
                doctor_id=doctor.id, code_hash=hash_reset_code(doctor.id, code),
                expires_at=expires, created_at=now,
            ))
        db.commit()
        return True
    except wa.SecretKeyMissing:
        db.rollback()
        logger.warning("Staff reset code not created: WHATSAPP_MESSAGES_KEY is missing")
        return False


def consume_staff_reset_code(db: Session, doctor, code) -> bool:
    """True only for the right, unexpired, unused code of the newest request. Every try is counted
    BEFORE it is compared, so parallel guesses cannot get past 5. On success the code is dead."""
    code = (code or "").strip()
    if not re.fullmatch(r"\d{6}", code):
        return False
    now = now_ist_naive()
    row = db.query(StaffResetCode).filter(
        StaffResetCode.doctor_id == doctor.id, StaffResetCode.used == False,  # noqa: E712
        StaffResetCode.expires_at > now,
    ).order_by(StaffResetCode.id.desc()).first()
    if row is None:
        return False
    counted = db.query(StaffResetCode).filter(
        StaffResetCode.id == row.id, StaffResetCode.used == False,  # noqa: E712
        StaffResetCode.attempts < MAX_ATTEMPTS,
    ).update({StaffResetCode.attempts: StaffResetCode.attempts + 1}, synchronize_session=False)
    db.commit()
    if counted != 1:
        return False
    if not hmac.compare_digest(hash_reset_code(doctor.id, code), row.code_hash):
        return False
    consumed = db.query(StaffResetCode).filter(
        StaffResetCode.id == row.id, StaffResetCode.used == False  # noqa: E712
    ).update({StaffResetCode.used: True}, synchronize_session=False)
    db.commit()
    return consumed == 1


def purge_old_staff_reset_codes(db: Session) -> int:
    """Scheduler: delete code rows that expired more than a day ago."""
    cutoff = now_ist_naive() - timedelta(days=KEEP_USED_DAYS)
    n = db.query(StaffResetCode).filter(StaffResetCode.expires_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return n