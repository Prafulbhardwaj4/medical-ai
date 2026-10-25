"""Patient forgot-password codes (the ONLY OTP in the system).

A request makes a random 6-digit code, stores only its HMAC, and puts the WhatsApp message with the
code in the staff messages list (visible to the super admin and the admin of the patient's
registering hospital). The code is valid 10 minutes, allows 5 tries, works once, and a new request
kills the earlier code. The readable code is never logged and never returned by any API."""
import hashlib
import hmac
import logging
import re
import secrets
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.patient import Patient
from app.models.patient_reset_code import PatientResetCode
from app.services import whatsapp_messages as wa
from app.utils.phone import normalize_phone
from app.utils.timezone import now_ist_naive

logger = logging.getLogger("patient_reset")

CODE_VALID_MINUTES = wa.OTP_VALID_MINUTES  # 10
MAX_ATTEMPTS = 5
MAX_CODES_PER_HOUR = 3  # per mobile number
KEEP_USED_DAYS = 1


def hash_reset_code(account_id: int, code: str) -> str:
    """Keyed hash (HMAC-SHA256 with the server secret)."""
    return hmac.new(
        settings.SECRET_KEY.encode(), f"portal-reset-v2:{account_id}:{code}".encode(), hashlib.sha256
    ).hexdigest()


def _registering_patient(db: Session, account):
    """The hospital record this number was first registered under (lowest id)."""
    stripped = func.replace(func.replace(func.replace(Patient.phone, " ", ""), "-", ""), "+", "")
    rows = db.query(Patient).filter(stripped.like(f"%{account.phone}")).order_by(Patient.id).all()
    for p in rows:
        if normalize_phone(p.phone) == account.phone:
            return p
    return None


def issue_reset_code(db: Session, account) -> bool:
    """Creates a code and its list message. Returns False (and creates nothing) when the number
    already asked 3 times this hour or WHATSAPP_MESSAGES_KEY is missing. The caller gives the
    same answer either way, so nothing about the account can be learned from it."""
    now = now_ist_naive()
    recent = db.query(func.count(PatientResetCode.id)).filter(
        PatientResetCode.account_id == account.id, PatientResetCode.created_at >= now - timedelta(hours=1)
    ).scalar() or 0
    if recent >= MAX_CODES_PER_HOUR:
        return False
    patient = _registering_patient(db, account)
    code = f"{secrets.randbelow(1_000_000):06d}"  # never a fixed code
    expires = now + timedelta(minutes=CODE_VALID_MINUTES)
    try:
        with db.begin_nested():
            # A new request kills the earlier code and deletes its readable copy.
            wa.wipe_secrets_for_recipient(db, recipient_kind="portal_account", recipient_id=account.id,
                                          template_keys=[wa.T_FORGOT_OTP])
            db.query(PatientResetCode).filter(
                PatientResetCode.account_id == account.id, PatientResetCode.used == False  # noqa: E712
            ).update({PatientResetCode.used: True}, synchronize_session=False)
            full, masked = wa.build_forgot_otp(code)
            wa.enqueue_message(
                db, template_key=wa.T_FORGOT_OTP, text=full, masked_text=masked, secret=True,
                visibility=wa.VIS_ADMIN_SUPER, expires_at=expires,
                hospital_id=patient.hospital_id if patient else None,
                recipient_kind="portal_account", recipient_id=account.id,
                recipient_name=patient.name if patient else "Patient", recipient_role="patient",
                recipient_phone=account.phone,
            )
            db.add(PatientResetCode(
                account_id=account.id, code_hash=hash_reset_code(account.id, code),
                expires_at=expires, created_at=now,
            ))
        db.commit()
        return True
    except wa.SecretKeyMissing:
        db.rollback()
        logger.warning("Patient reset code not created: WHATSAPP_MESSAGES_KEY is missing")
        return False


def consume_reset_code(db: Session, account, code) -> bool:
    """True only for the right, unexpired, unused code of the newest request. Every try is counted
    BEFORE it is compared, so parallel guesses cannot get past 5. On success the code is dead."""
    code = (code or "").strip()
    if not re.fullmatch(r"\d{6}", code):
        return False
    now = now_ist_naive()
    row = db.query(PatientResetCode).filter(
        PatientResetCode.account_id == account.id, PatientResetCode.used == False,  # noqa: E712
        PatientResetCode.expires_at > now,
    ).order_by(PatientResetCode.id.desc()).first()
    if row is None:
        return False
    counted = db.query(PatientResetCode).filter(
        PatientResetCode.id == row.id, PatientResetCode.used == False,  # noqa: E712
        PatientResetCode.attempts < MAX_ATTEMPTS,
    ).update({PatientResetCode.attempts: PatientResetCode.attempts + 1}, synchronize_session=False)
    db.commit()
    if counted != 1:
        return False
    if not hmac.compare_digest(hash_reset_code(account.id, code), row.code_hash):
        return False
    consumed = db.query(PatientResetCode).filter(
        PatientResetCode.id == row.id, PatientResetCode.used == False  # noqa: E712
    ).update({PatientResetCode.used: True}, synchronize_session=False)
    db.commit()
    return consumed == 1


def purge_old_reset_codes(db: Session) -> int:
    """Scheduler: delete code rows that are used or expired for more than a day."""
    cutoff = now_ist_naive() - timedelta(days=KEEP_USED_DAYS)
    n = db.query(PatientResetCode).filter(PatientResetCode.expires_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return n