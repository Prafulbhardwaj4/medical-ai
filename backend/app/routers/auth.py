from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.doctor import Doctor
from app.schemas.doctor import DoctorCreate, DoctorLogin, DoctorOut, Token
from app.utils.auth import hash_password, verify_password, create_access_token
from app.utils.auth import blacklist_token, get_current_doctor
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request

security = HTTPBearer()

limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/signup", response_model=DoctorOut, status_code=201)
def signup(payload: DoctorCreate, db: Session = Depends(get_db)):
    existing = db.query(Doctor).filter(Doctor.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    doctor = Doctor(
        title=payload.title,
        name=payload.name,
        email=payload.email,
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
    doctor = db.query(Doctor).filter(Doctor.email == payload.email).first()
    if not doctor or not verify_password(payload.password, doctor.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token({"sub": str(doctor.id)})
    return {"access_token": token, "token_type": "bearer", "doctor": doctor}

@router.get("/me", response_model=DoctorOut)
def me(current_doctor: Doctor = Depends(get_db)):
    # Will wire up properly in main.py
    pass

@router.post("/logout")
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    blacklist_token(credentials.credentials)
    return {"message": "Logged out successfully"}

