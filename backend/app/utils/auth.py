import calendar
import hashlib
import random
import secrets
from passlib.context import CryptContext
from app.utils.jwt_compat import JWTError, jwt
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.config import settings, _is_production
from app.database import get_db
from app.models.blacklisted_token import BlacklistedToken
from app.utils.timezone import now_ist, now_ist_naive, ist_today, ist_day_bounds, ist_date, ist_day_bounds_utc, utc_naive_to_ist_date

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    now = datetime.utcnow()
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": now})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def check_password_strength(new_password: str, email: str = None, name: str = None, extras=()) -> None:
    if len(new_password) < 8 or not any(c.isdigit() for c in new_password) or not any(c.isupper() for c in new_password):
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters, with 1 number and 1 capital letter")
    from app.utils.common_passwords import is_common_password, contains_personal_info
    if is_common_password(new_password):
        raise HTTPException(status_code=400, detail="This password is too common. Please choose a harder one.")
    if contains_personal_info(new_password, email, name, extras):
        raise HTTPException(status_code=400, detail="Your password must not contain your name, email or phone number.")


def generate_temp_password(length: int = 10) -> str:
    """Random one-time password for new/reset staff accounts. Always satisfies
    the strength rule (upper + lower + digit); ambiguous characters excluded."""
    upper, lower, digits = "ABCDEFGHJKMNPQRSTUVWXYZ", "abcdefghjkmnpqrstuvwxyz", "23456789"
    chars = [secrets.choice(upper), secrets.choice(lower), secrets.choice(digits)]
    chars += [secrets.choice(upper + lower + digits) for _ in range(length - 3)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def token_predates_password_change(payload: dict, changed_at) -> bool:
    """True if the token was issued before the account's last password change.
    changed_at is UTC-naive. Tokens without iat (issued before this check
    existed) are only accepted while the password has never been changed."""
    if changed_at is None:
        return False
    iat = payload.get("iat")
    if iat is None:
        return True
    return int(iat) < calendar.timegm(changed_at.utctimetuple())

CAPTCHA_EXPIRE_MINUTES = 5
CAPTCHA_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no O/o/0, I/i/l/L/1 — avoids ambiguous reads. Verification is already case-insensitive (see verify_captcha_token), so mixing case here is purely visual.

def generate_captcha_code(length: int = 5) -> str:
    return "".join(secrets.choice(CAPTCHA_ALPHABET) for _ in range(length))

def generate_captcha_svg(code: str) -> str:
    """Hand-built distorted-text SVG — no image library needed/available in
    this environment. Random rotation + noise lines/dots per render."""
    # Vector shapes only (no <text>): the answer cannot be read from the markup. See utils/captcha_font.py.
    from app.utils.captcha_font import render_captcha_svg
    return render_captcha_svg(code)

def create_captcha_token(answer: str) -> str:
    """Stores the expected answer SERVER-SIDE and returns only an opaque id.
    (The old version put the answer inside a signed JWT, which anyone could
    decode.) Signature kept so callers don't change."""
    from app.database import SessionLocal
    from app.models.captcha_challenge import CaptchaChallenge
    challenge_id = secrets.token_urlsafe(24)
    now = datetime.utcnow()
    db = SessionLocal()
    try:
        db.query(CaptchaChallenge).filter(CaptchaChallenge.expires_at < now).delete(synchronize_session=False)
        db.add(CaptchaChallenge(
            id=challenge_id,
            answer=str(answer).strip().lower(),
            expires_at=now + timedelta(minutes=CAPTCHA_EXPIRE_MINUTES),
        ))
        db.commit()
    finally:
        db.close()
    return challenge_id

def verify_captcha_token(token: str, submitted_answer: str) -> bool:
    """Single-use: the challenge row is deleted on the first attempt, right
    or wrong, so a solved captcha can never be replayed. Case-insensitive
    (upper/lower pairs like c/C, s/S, v/V look identical in the image)."""
    from app.database import SessionLocal
    from app.models.captcha_challenge import CaptchaChallenge
    if (
        settings.DEV_CAPTCHA_ANSWER
        and not _is_production(settings)
        and submitted_answer == settings.DEV_CAPTCHA_ANSWER
    ):
        return True
    if not token or not submitted_answer or len(token) > 64:
        return False
    db = SessionLocal()
    try:
        row = db.query(CaptchaChallenge).filter(CaptchaChallenge.id == token).first()
        if row is None:
            return False
        expected, expires_at = row.answer, row.expires_at  # read before the commit expires the row
        deleted = db.query(CaptchaChallenge).filter(CaptchaChallenge.id == token).delete(synchronize_session=False)
        db.commit()
        if deleted != 1:  # a concurrent request already consumed it
            return False
        if expires_at < datetime.utcnow():
            return False
        return secrets.compare_digest(
            expected.encode("utf-8"),
            str(submitted_answer).strip().lower().encode("utf-8"),
        )
    finally:
        db.close()

PASSWORD_RESET_EXPIRE_MINUTES = 10

def create_password_reset_token(doctor_id: int, otp: str) -> str:
    """Issued after a correct forgot-password OTP. Lets the frontend set a
    new password without ever needing the old one. The OTP is embedded too,
    so reset-password can reject reusing it as the new password."""
    expire = datetime.utcnow() + timedelta(minutes=PASSWORD_RESET_EXPIRE_MINUTES)
    return jwt.encode(
        {"type": "password_reset", "sub": str(doctor_id), "otp": otp, "exp": expire},
        settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )

def verify_password_reset_token(token: str):
    """Returns (doctor_id, otp) on success, or (None, None) if invalid/expired."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None, None
    if payload.get("type") != "password_reset":
        return None, None
    doctor_id = payload.get("sub")
    if not doctor_id:
        return None, None
    return int(doctor_id), payload.get("otp")

PASSWORD_SETUP_EXPIRE_MINUTES = 10

def create_password_setup_token(doctor_id: int) -> str:
    """Issued at login when the temp password was correct (captcha already
    passed). Lets set-new-password run without a second captcha."""
    now = datetime.utcnow()
    return jwt.encode(
        {"type": "password_setup", "sub": str(doctor_id), "iat": now,
         "exp": now + timedelta(minutes=PASSWORD_SETUP_EXPIRE_MINUTES)},
        settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )

def verify_password_setup_token(token: str):
    """Returns doctor_id, or None if invalid/expired."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None
    if payload.get("type") != "password_setup" or not payload.get("sub"):
        return None
    return int(payload["sub"])

TOTP_PENDING_EXPIRE_MINUTES = 5

def create_totp_pending_token(doctor_id: int) -> str:
    """Issued after the Super Admin's password + captcha passed, before the 2FA code.
    Has a 'type' claim, so get_current_doctor refuses it as a login."""
    now = datetime.utcnow()
    return jwt.encode(
        {"type": "totp_pending", "sub": str(doctor_id), "iat": now,
         "exp": now + timedelta(minutes=TOTP_PENDING_EXPIRE_MINUTES)},
        settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )

def verify_totp_pending_token(token: str):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None
    if payload.get("type") != "totp_pending" or not payload.get("sub"):
        return None
    return int(payload["sub"])

def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None

def blacklist_token(token: str, db: Session):
    now = now_ist_naive()
    # Purge: the longest-lived token (portal, 7 days) can't outlive 8 days, so
    # older blacklist rows are dead weight. Runs on every logout - no cron needed.
    db.query(BlacklistedToken).filter(
        BlacklistedToken.blacklisted_at < now - timedelta(days=8)
    ).delete(synchronize_session=False)
    token_hash = hash_token(token)
    if db.query(BlacklistedToken.id).filter(BlacklistedToken.token_hash == token_hash).first() is None:
        db.add(BlacklistedToken(token_hash=token_hash, blacklisted_at=now))
    db.commit()


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()

def is_token_blacklisted(token: str, db: Session) -> bool:
    # New rows hold only the hash. The old raw column is still checked while old rows exist (they are purged within 8 days).
    from sqlalchemy import or_
    return db.query(BlacklistedToken.id).filter(
        or_(BlacklistedToken.token_hash == hash_token(token), BlacklistedToken.token == token)
    ).first() is not None

def get_current_doctor(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    from app.models.doctor import Doctor
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise credentials_exception
    # Only real staff session tokens (no "type"/"purpose" claim) may act as a
    # login. Portal, password-reset, password-setup tokens share this signing
    # key and were previously accepted here.
    if payload.get("type") or payload.get("purpose"):
        raise credentials_exception
    doctor_id: int = payload.get("sub")
    if doctor_id is None:
        raise credentials_exception
    from sqlalchemy import exists, or_
    from app.models.hospital import Hospital
    token = credentials.credentials
    # ONE query for the account, its hospital and "is this token blacklisted" (checked fresh on every
    # request: nothing here is cached).
    blacklisted = exists().where(or_(BlacklistedToken.token_hash == hash_token(token), BlacklistedToken.token == token))
    row = db.query(Doctor, Hospital, blacklisted.label("token_blacklisted")).outerjoin(
        Hospital, Hospital.id == Doctor.hospital_id
    ).filter(Doctor.id == int(doctor_id)).first()
    if row is None:
        raise credentials_exception
    doctor, hospital, token_blacklisted = row
    if token_blacklisted:
        raise credentials_exception
    if not doctor.is_active:
        raise credentials_exception
    if token_predates_password_change(payload, doctor.password_changed_at):
        raise credentials_exception
    if doctor.role.value != "super_admin":
        from app.utils.pilot_lifecycle import ensure_pilot_lifecycle
        pilot_expired = ensure_pilot_lifecycle(db, hospital) if hospital else False  # pilot past grace: deactivated at the first request
        if not hospital or not hospital.is_active or pilot_expired:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"This hospital's account is deactivated. Please contact {settings.BRAND_NAME} support.",
                headers={"WWW-Authenticate": "Bearer"},
            )
    return doctor