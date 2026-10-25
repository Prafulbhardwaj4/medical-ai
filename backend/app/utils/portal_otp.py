import secrets

from app.config import settings


def temp_password_enabled() -> bool:
    return bool(settings.PORTAL_TEMP_PASSWORD)


def is_temp_password(password: str) -> bool:
    """True if `password` is the temporary first-login password (when enabled)."""
    if not settings.PORTAL_TEMP_PASSWORD:
        return False
    return secrets.compare_digest((password or "").encode(), settings.PORTAL_TEMP_PASSWORD.encode())


def issue_temporary_password() -> str:
    """The password a patient account starts with. Today: the one fixed temporary
    password. When WhatsApp is live, set PORTAL_TEMP_PASSWORD="" and this returns a
    random one per patient, which deliver_temp_password() must send to them."""
    if settings.PORTAL_TEMP_PASSWORD:
        return settings.PORTAL_TEMP_PASSWORD
    from app.utils.auth import generate_temp_password
    return generate_temp_password()