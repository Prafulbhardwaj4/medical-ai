from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.config import settings
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
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

CAPTCHA_EXPIRE_MINUTES = 5

def create_captcha_token(answer: int) -> str:
    """Signs the expected answer into a short-lived token so the server
    doesn't need to store the captcha anywhere. type=captcha keeps this
    from ever being accepted as a real access token."""
    expire = datetime.utcnow() + timedelta(minutes=CAPTCHA_EXPIRE_MINUTES)
    return jwt.encode(
        {"type": "captcha", "answer": answer, "exp": expire},
        settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )

def verify_captcha_token(token: str, submitted_answer: str) -> bool:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return False
    if payload.get("type") != "captcha":
        return False
    try:
        return int(payload.get("answer")) == int(str(submitted_answer).strip())
    except (TypeError, ValueError):
        return False

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

def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None

def blacklist_token(token: str, db: Session):
    entry = BlacklistedToken(token=token, blacklisted_at=now_ist_naive())
    db.add(entry)
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
    if doctor.role.value != "super_admin":
        hospital = db.query(Hospital).filter(Hospital.id == doctor.hospital_id).first()
        if not hospital or not hospital.is_active:
            raise credentials_exception
    return doctor