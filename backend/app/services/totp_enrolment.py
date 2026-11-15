"""One-time 2FA enrolment codes for super admins (see models/totp_enrolment.py)."""
import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from app.models.totp_enrolment import SuperAdminEnrolmentCode
from app.utils.timezone import now_ist_naive

_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_VALID_HOURS = 24


def _normalise(code: str) -> str:
    return re.sub(r"[\s-]+", "", str(code or "")).upper()


def hash_code(code: str) -> str:
    return hashlib.sha256(_normalise(code).encode("utf-8")).hexdigest()


def issue_enrolment_code(db, doctor) -> str:
    """Creates a new code for this account (older unused codes stop working) and returns it ONCE in plain text."""
    now = now_ist_naive()
    for old in db.query(SuperAdminEnrolmentCode).filter(
        SuperAdminEnrolmentCode.doctor_id == doctor.id,
        SuperAdminEnrolmentCode.used_at.is_(None),
        SuperAdminEnrolmentCode.expires_at > now,
    ).all():
        old.expires_at = now
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(16))
    code = "-".join(raw[i:i + 4] for i in range(0, 16, 4))
    db.add(SuperAdminEnrolmentCode(
        doctor_id=doctor.id,
        code_hash=hash_code(code),
        expires_at=now + timedelta(hours=CODE_VALID_HOURS),
    ))
    db.commit()
    return code


def claim_enrolment_code(db, doctor, supplied) -> bool:
    """True if the supplied code is this account's current, unused, unexpired code. It is marked
    claimed (the setup screen may be reloaded) and only becomes spent when enrolment is confirmed."""
    now = now_ist_naive()
    wanted = hash_code(supplied)
    match = None
    for row in db.query(SuperAdminEnrolmentCode).filter(
        SuperAdminEnrolmentCode.doctor_id == doctor.id,
        SuperAdminEnrolmentCode.used_at.is_(None),
        SuperAdminEnrolmentCode.expires_at > now,
    ).all():
        if hmac.compare_digest(row.code_hash, wanted):
            match = row
    if match is None:
        return False
    match.claimed_at = now
    db.commit()
    return True


def open_enrolment(db, doctor):
    """The claimed, unspent, unexpired code row for this account, or None."""
    now = now_ist_naive()
    return db.query(SuperAdminEnrolmentCode).filter(
        SuperAdminEnrolmentCode.doctor_id == doctor.id,
        SuperAdminEnrolmentCode.used_at.is_(None),
        SuperAdminEnrolmentCode.claimed_at.isnot(None),
        SuperAdminEnrolmentCode.expires_at > now,
    ).first()