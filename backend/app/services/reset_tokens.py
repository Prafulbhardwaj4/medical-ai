"""Short-lived token for the LAST step of forgot-password (choosing the new password), handed out only
after the 6-digit code was accepted. It carries the account's password-change stamp, so it stops working
the moment the password changes (one reset per code), and it expires after 10 minutes."""
from datetime import datetime, timedelta

from jose import JWTError, jwt

from app.config import settings

RESET_TOKEN_MINUTES = 10
_PURPOSE = "password_reset_v2"


def _stamp(password_changed_at) -> str:
    return str(int(password_changed_at.timestamp())) if password_changed_at else "0"


def create_reset_token(kind: str, subject_id: int, password_changed_at) -> str:
    """kind is "staff" or "patient", so a token for one kind can never be used for the other."""
    payload = {
        "sub": str(subject_id), "kind": kind, "stamp": _stamp(password_changed_at), "purpose": _PURPOSE,
        "exp": datetime.utcnow() + timedelta(minutes=RESET_TOKEN_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def read_reset_token(token: str, kind: str):
    """Returns (subject_id, stamp), or (None, None) when the token is invalid, expired or of another kind."""
    try:
        payload = jwt.decode(token or "", settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("purpose") != _PURPOSE or payload.get("kind") != kind:
            return None, None
        return int(payload["sub"]), str(payload["stamp"])
    except (JWTError, KeyError, TypeError, ValueError):
        return None, None


def current_stamp(password_changed_at) -> str:
    return _stamp(password_changed_at)