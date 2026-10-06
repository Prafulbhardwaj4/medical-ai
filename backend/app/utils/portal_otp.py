import hashlib
import logging
import secrets

from app.config import settings, _is_production

OTP_TTL_MINUTES = 10
logger = logging.getLogger("portal_otp")


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


def generate_otp() -> str:
    """Today: the fixed OTP. With PORTAL_FIXED_OTP="" it is a random 6-digit code."""
    if settings.PORTAL_FIXED_OTP:
        return settings.PORTAL_FIXED_OTP
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(account_id: int, otp: str) -> str:
    return hashlib.sha256(f"portal-otp-v1:{settings.SECRET_KEY}:{account_id}:{otp}".encode()).hexdigest()


def deliver_otp(phone: str, otp: str) -> None:
    """Send the OTP to the patient's WhatsApp. Not connected yet (needs Meta business
    verification): this is the single place to plug the sender in later."""
    if not _is_production(settings):
        logger.warning("[DEV] Portal OTP for %s is %s (WhatsApp sending is not connected)", phone, otp)
    else:
        logger.warning("Portal OTP generated for %s but WhatsApp sending is not connected", phone)