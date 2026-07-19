from datetime import datetime, timedelta

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.portal import PatientAccount

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
portal_security = HTTPBearer()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_portal_access_token(account_id: int) -> str:
    payload = {
        "sub": str(account_id),
        "type": "portal",
        "exp": datetime.utcnow() + timedelta(minutes=settings.PORTAL_ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_invite_token(phone: str, hospital_id: int, patient_id: int) -> str:
    payload = {
        "phone": phone,
        "hospital_id": hospital_id,
        "patient_id": patient_id,
        "purpose": "invite",
        "exp": datetime.utcnow() + timedelta(days=settings.PORTAL_INVITE_EXPIRE_DAYS),
    }
    return jwt.encode(payload, settings.PORTAL_INVITE_SECRET, algorithm=settings.ALGORITHM)


def decode_invite_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.PORTAL_INVITE_SECRET, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=400, detail="Invalid or expired invite link")


def create_link_confirm_token(phone: str, hospital_id: int, patient_id: int, display_name: str) -> str:
    payload = {
        "phone": phone,
        "hospital_id": hospital_id,
        "patient_id": patient_id,
        "display_name": display_name,
        "purpose": "link_confirm",
        "exp": datetime.utcnow() + timedelta(hours=settings.PORTAL_LINK_CONFIRM_EXPIRE_HOURS),
    }
    return jwt.encode(payload, settings.PORTAL_INVITE_SECRET, algorithm=settings.ALGORITHM)


def decode_link_confirm_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.PORTAL_INVITE_SECRET, algorithms=[settings.ALGORITHM])
        if payload.get("purpose") != "link_confirm":
            raise JWTError()
        return payload
    except JWTError:
        raise HTTPException(status_code=400, detail="This confirmation link is invalid or has expired")


def get_current_patient_account(
    credentials: HTTPAuthorizationCredentials = Depends(portal_security),
    db: Session = Depends(get_db),
) -> PatientAccount:
    try:
        payload = jwt.decode(credentials.credentials, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "portal":
            raise HTTPException(status_code=401, detail="Not a portal session")
        account_id = int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    account = db.query(PatientAccount).filter(PatientAccount.id == account_id).first()
    if not account or not account.is_active:
        raise HTTPException(status_code=401, detail="Account not found")
    return account