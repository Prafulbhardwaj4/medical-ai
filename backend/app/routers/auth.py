from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.database import get_db
from app.models.doctor import Doctor
from app.schemas.doctor import DoctorCreate, DoctorLogin, DoctorOut, Token
from app.utils.auth import hash_password, verify_password, create_access_token
from app.utils.auth import blacklist_token, get_current_doctor
from slowapi import Limiter
from slowapi.util import get_remote_address

security = HTTPBearer()
limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/auth", tags=["auth"])

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

@router.post("/signup", response_model=DoctorOut, status_code=201)
@limiter.limit("3/minute")
def signup(request: Request, payload: DoctorCreate, db: Session = Depends(get_db)):
    email = payload.email.lower().strip()
    existing = db.query(Doctor).filter(Doctor.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    doctor = Doctor(
        title=payload.title,
        name=payload.name,
        email=email,
        phone=payload.phone,
        specialization=payload.specialization,
        registration_number=payload.registration_number,
        clinic_name=payload.clinic_name,
        hashed_password=hash_password(payload.password)
    )
    db.add(doctor)
    db.commit()
    db.refresh(doctor)
    return doctor

@router.post("/login", response_model=Token)
@limiter.limit("5/minute")
def login(request: Request, payload: DoctorLogin, db: Session = Depends(get_db)):
    email = payload.email.lower().strip()
    doctor = db.query(Doctor).filter(Doctor.email == email).first()

    # Always return same error — don't reveal if email exists
    if not doctor:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Check if account is locked
    if doctor.locked_until and datetime.utcnow() < doctor.locked_until:
        minutes_left = int((doctor.locked_until - datetime.utcnow()).seconds / 60) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Account temporarily locked. Try again in {minutes_left} minute(s)."
        )

    # Reset lock if lockout period has passed
    if doctor.locked_until and datetime.utcnow() >= doctor.locked_until:
        doctor.failed_login_attempts = 0
        doctor.locked_until = None

    # Wrong password
    if not verify_password(payload.password, doctor.hashed_password):
        doctor.failed_login_attempts += 1
        if doctor.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
            doctor.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
            db.commit()
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed attempts. Account locked for {LOCKOUT_MINUTES} minutes."
            )
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Successful login — reset failed attempts
    doctor.failed_login_attempts = 0
    doctor.locked_until = None
    db.commit()

    token = create_access_token({"sub": str(doctor.id)})
    return {"access_token": token, "token_type": "bearer", "doctor": doctor}

@router.get("/me", response_model=DoctorOut)
def me(current_doctor: Doctor = Depends(get_current_doctor)):
    return current_doctor

@router.post("/logout")
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    blacklist_token(credentials.credentials)
    return {"message": "Logged out successfully"}