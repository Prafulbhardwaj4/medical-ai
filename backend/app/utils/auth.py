import calendar
import random
import secrets
from passlib.context import CryptContext
from jose import JWTError, jwt
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


def check_password_strength(new_password: str) -> None:
    if len(new_password) < 8 or not any(c.isdigit() for c in new_password) or not any(c.isupper() for c in new_password):
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters, with 1 number and 1 capital letter")


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
CAPTCHA_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"  # no O/o/0, I/i/l/L/1 — avoids ambiguous reads. Verification is already case-insensitive (see verify_captcha_token), so mixing case here is purely visual.

def generate_captcha_code(length: int = 5) -> str:
    return "".join(secrets.choice(CAPTCHA_ALPHABET) for _ in range(length))

def generate_captcha_svg(code: str) -> str:
    """Hand-built distorted-text SVG — no image library needed/available in
    this environment. Random rotation + noise lines/dots per render."""
    width, height = 160, 60
    colors = ["#0f172a", "#334155", "#0d9488", "#7c3aed", "#b91c1c"]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">']
    parts.append(f'<rect width="{width}" height="{height}" fill="#f1f5f9" rx="8"/>')
    for _ in range(4):
        x1, y1 = random.randint(0, width), random.randint(0, height)
        x2, y2 = random.randint(0, width), random.randint(0, height)
        parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#cbd5e1" stroke-width="2"/>')
    spacing = width / (len(code) + 1)
    for i, ch in enumerate(code):
        x = spacing * (i + 1)
        y = height / 2 + random.randint(-6, 6)
        rotate = random.randint(-25, 25)
        color = random.choice(colors)
        parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-size="28" font-family="Arial, sans-serif" '
            f'font-weight="700" fill="{color}" text-anchor="middle" '
            f'transform="rotate({rotate} {x:.1f} {y:.1f})">{ch}</text>'
        )
    for _ in range(15):
        cx, cy = random.randint(0, width), random.randint(0, height)
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="1.4" fill="#94a3b8"/>')
    parts.append('</svg>')
    return "".join(parts)

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
    if db.query(BlacklistedToken).filter(BlacklistedToken.token == token).first() is None:
        db.add(BlacklistedToken(token=token, blacklisted_at=now))
    db.commit()

def is_token_blacklisted(token: str, db: Session) -> bool:
    return db.query(BlacklistedToken).filter(BlacklistedToken.token == token).first() is not None

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
    if is_token_blacklisted(credentials.credentials, db):
        raise credentials_exception
    doctor_id: int = payload.get("sub")
    if doctor_id is None:
        raise credentials_exception
    from app.models.hospital import Hospital
    doctor = db.query(Doctor).filter(Doctor.id == int(doctor_id)).first()
    if doctor is None:
        raise credentials_exception
    if not doctor.is_active:
        raise credentials_exception
    if token_predates_password_change(payload, doctor.password_changed_at):
        raise credentials_exception
    if doctor.role.value != "super_admin":
        hospital = db.query(Hospital).filter(Hospital.id == doctor.hospital_id).first()
        if not hospital or not hospital.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="This hospital's account is deactivated. Please contact MedScribe support.",
                headers={"WWW-Authenticate": "Bearer"},
            )
    return doctor