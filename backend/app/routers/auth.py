import random
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.database import get_db
from app.models.doctor import Doctor
from app.schemas.doctor import DoctorCreate, DoctorLogin, DoctorOut, EditMeIn, Token, CaptchaOut, StaffLoginResultOut, SetNewPasswordIn
from app.schemas.doctor import ForgotPasswordRequestIn, ForgotPasswordVerifyIn, ForgotPasswordVerifyOut, ResetPasswordIn
from app.utils.auth import hash_password, verify_password, create_access_token
from app.utils.auth import blacklist_token, get_current_doctor
from app.utils.auth import create_captcha_token, verify_captcha_token
from app.utils.auth import create_password_reset_token, verify_password_reset_token
from app.config import settings
from app.utils.timezone import now_ist_naive
from app.utils.audit import log_action
from slowapi import Limiter
from slowapi.util import get_remote_address

security = HTTPBearer()
limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/auth", tags=["auth"])

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

@router.post("/signup", status_code=403)
def signup(request: Request):
    raise HTTPException(status_code=403, detail="Public signup is disabled. Contact your hospital admin.")

@router.get("/captcha", response_model=CaptchaOut)
@limiter.limit("20/minute")
def get_captcha(request: Request):
    a = random.randint(1, 9)
    b = random.randint(1, 9)
    return CaptchaOut(question=f"What is {a} + {b}?", token=create_captcha_token(a + b))

@router.post("/login", response_model=StaffLoginResultOut)
@limiter.limit("5/minute")
def login(request: Request, payload: DoctorLogin, db: Session = Depends(get_db)):
    if not verify_captcha_token(payload.captcha_token, payload.captcha_answer):
        raise HTTPException(status_code=400, detail="Incorrect captcha. Please try again.")

    email = payload.email.lower().strip()
    doctor = db.query(Doctor).filter(Doctor.email == email).first()

    if not doctor:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Check if account is locked
    if doctor.locked_until and now_ist_naive() < doctor.locked_until:
        minutes_left = int((doctor.locked_until - now_ist_naive()).seconds / 60) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Account temporarily locked. Try again in {minutes_left} minute(s)."
        )

    # Reset lock if lockout period has passed
    if doctor.locked_until and now_ist_naive() >= doctor.locked_until:
        doctor.failed_login_attempts = 0
        doctor.locked_until = None

    # Check if account is active
    if not doctor.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated. Contact your admin.")
    
    # Check if the doctor's hospital is active
    if doctor.hospital_id and doctor.hospital and not doctor.hospital.is_active:
        raise HTTPException(status_code=403, detail="Your hospital account has been deactivated. Contact support.")

    # Wrong password
    if not verify_password(payload.password, doctor.hashed_password):
        doctor.failed_login_attempts += 1
        if doctor.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
            doctor.locked_until = now_ist_naive() + timedelta(minutes=LOCKOUT_MINUTES)
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

    if doctor.must_change_password:
        # Correct temp password + correct captcha — but this account still
        # needs to set its own password before it gets a real session.
        return StaffLoginResultOut(status="needs_password_change")

    token = create_access_token({"sub": str(doctor.id), "role": doctor.role.value})
    return StaffLoginResultOut(status="success", access_token=token, doctor=doctor)

@router.post("/set-new-password", response_model=Token)
@limiter.limit("5/minute")
def set_new_password(request: Request, payload: SetNewPasswordIn, db: Session = Depends(get_db)):
    if not verify_captcha_token(payload.captcha_token, payload.captcha_answer):
        raise HTTPException(status_code=400, detail="Incorrect captcha. Please try again.")

    email = payload.email.lower().strip()
    doctor = db.query(Doctor).filter(Doctor.email == email).first()
    if not doctor:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not doctor.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated. Contact your admin.")

    if not verify_password(payload.old_password, doctor.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not doctor.must_change_password:
        raise HTTPException(status_code=400, detail="This account has already set its password. Please log in normally.")

    new_password = payload.new_password
    if len(new_password) < 8 or not any(c.isdigit() for c in new_password) or not any(c.isupper() for c in new_password):
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters, with 1 number and 1 capital letter")
    if new_password == payload.old_password:
        raise HTTPException(status_code=400, detail="New password must be different from the temporary one")

    doctor.hashed_password = hash_password(new_password)
    doctor.must_change_password = False
    doctor.failed_login_attempts = 0
    doctor.locked_until = None
    db.commit()
    db.refresh(doctor)

    log_action(
        db, doctor,
        action="password_changed_first_login",
        target_type="doctor",
        target_id=doctor.id,
        target_label=f"{doctor.title} {doctor.name}",
        hospital_id=doctor.hospital_id
    )

    token = create_access_token({"sub": str(doctor.id), "role": doctor.role.value})
    return {"access_token": token, "token_type": "bearer", "doctor": doctor}

@router.post("/forgot-password/request")
@limiter.limit("5/minute")
def forgot_password_request(request: Request, payload: ForgotPasswordRequestIn, db: Session = Depends(get_db)):
    if not verify_captcha_token(payload.captcha_token, payload.captcha_answer):
        raise HTTPException(status_code=400, detail="Incorrect captcha. Please try again.")

    email = payload.email.lower().strip()
    doctor = db.query(Doctor).filter(Doctor.email == email).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="No staff account found with this email.")
    if not doctor.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated. Contact your admin.")

    # TODO: send a real WhatsApp OTP here once delivery is wired up. For now
    # every account accepts settings.STAFF_FORGOT_PASSWORD_OTP (see config.py).
    return {"message": "An OTP has been sent to the registered mobile number."}

@router.post("/forgot-password/verify", response_model=ForgotPasswordVerifyOut)
@limiter.limit("5/minute")
def forgot_password_verify(request: Request, payload: ForgotPasswordVerifyIn, db: Session = Depends(get_db)):
    email = payload.email.lower().strip()
    doctor = db.query(Doctor).filter(Doctor.email == email).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="No staff account found with this email.")

    if payload.otp.strip() != settings.STAFF_FORGOT_PASSWORD_OTP:
        raise HTTPException(status_code=400, detail="Incorrect OTP. Please try again.")

    return ForgotPasswordVerifyOut(reset_token=create_password_reset_token(doctor.id, payload.otp.strip()))

@router.post("/reset-password", response_model=Token)
@limiter.limit("5/minute")
def reset_password(request: Request, payload: ResetPasswordIn, db: Session = Depends(get_db)):
    doctor_id, otp = verify_password_reset_token(payload.reset_token)
    if doctor_id is None:
        raise HTTPException(status_code=400, detail="This reset link has expired. Please request a new OTP.")

    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Account not found")
    if not doctor.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated. Contact your admin.")

    new_password = payload.new_password
    if len(new_password) < 8 or not any(c.isdigit() for c in new_password) or not any(c.isupper() for c in new_password):
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters, with 1 number and 1 capital letter")
    if otp and new_password == otp:
        raise HTTPException(status_code=400, detail="New password cannot be the same as the OTP.")
    if verify_password(new_password, doctor.hashed_password):
        raise HTTPException(status_code=400, detail="New password must be different from your previous password.")

    doctor.hashed_password = hash_password(new_password)
    doctor.must_change_password = False
    doctor.failed_login_attempts = 0
    doctor.locked_until = None
    db.commit()
    db.refresh(doctor)

    log_action(
        db, doctor,
        action="password_reset_via_otp",
        target_type="doctor",
        target_id=doctor.id,
        target_label=f"{doctor.title} {doctor.name}",
        hospital_id=doctor.hospital_id
    )

    token = create_access_token({"sub": str(doctor.id), "role": doctor.role.value})
    return {"access_token": token, "token_type": "bearer", "doctor": doctor}

@router.get("/me", response_model=DoctorOut)
def me(current_doctor: Doctor = Depends(get_current_doctor)):
    return current_doctor

@router.patch("/me", response_model=DoctorOut)
def update_me(
    payload: EditMeIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    name = payload.name.strip()
    phone = payload.phone.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if not phone:
        raise HTTPException(status_code=400, detail="Contact number is required")

    current_doctor.name = name
    current_doctor.phone = phone
    current_doctor.registration_number = (payload.registration_number or "").strip()
    if current_doctor.role.value == "doctor":
        current_doctor.title = "Dr."
    elif payload.title in ("Mr.", "Ms."):
        current_doctor.title = payload.title
    db.commit()
    db.refresh(current_doctor)

    log_action(
        db, current_doctor,
        action="self_details_updated",
        target_type="doctor",
        target_id=current_doctor.id,
        target_label=f"{current_doctor.title} {current_doctor.name}",
        hospital_id=current_doctor.hospital_id
    )
    return current_doctor

@router.post("/logout")
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    current_doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db)
):
    blacklist_token(credentials.credentials, db)
    return {"message": "Logged out successfully"}