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