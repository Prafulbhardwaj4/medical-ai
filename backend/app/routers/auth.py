from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.database import get_db
from app.models.doctor import Doctor
from app.schemas.doctor import DoctorCreate, DoctorLogin, DoctorOut, EditMeIn, Token, CaptchaOut, StaffLoginResultOut, SetNewPasswordIn, ChangePasswordIn
from app.schemas.doctor import ForgotPasswordRequestIn, ForgotPasswordVerifyIn, ForgotPasswordVerifyOut, ResetPasswordIn
from app.utils.auth import hash_password, verify_password, create_access_token
from app.utils.auth import blacklist_token, get_current_doctor, decode_access_token
from app.utils.auth import create_captcha_token, verify_captcha_token, generate_captcha_code, generate_captcha_svg
from app.utils.auth import create_password_reset_token, verify_password_reset_token
from app.utils.auth import create_password_setup_token, verify_password_setup_token, check_password_strength
from app.config import settings
from app.utils.timezone import now_ist_naive
from app.utils.audit import log_action
from app.utils.rate_limit import limiter
from app.utils.phone import normalize_phone
import json
from pydantic import BaseModel
from app.config import _is_production
from app.utils.auth import create_totp_pending_token, verify_totp_pending_token
from app.utils import totp as totp_util

security = HTTPBearer()
router = APIRouter(prefix="/auth", tags=["auth"])

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
_TIMING_HASH = hash_password("timing-equalizer-Aa1")  # used only to equalize login response time

@router.post("/signup", status_code=403)
def signup(request: Request):
    raise HTTPException(status_code=403, detail="Public signup is disabled. Contact your hospital admin.")

@router.get("/captcha", response_model=CaptchaOut)
@limiter.limit("120/minute")
def get_captcha(request: Request):
    code = generate_captcha_code()
    return CaptchaOut(svg=generate_captcha_svg(code), token=create_captcha_token(code))

# Per-IP ceiling is deliberately high: a hospital's staff share one public IP.
# Real brute-force protection is the per-account lockout below (5 wrong
# passwords -> 15 min) plus the single-use captcha on every attempt.
@router.post("/login", response_model=StaffLoginResultOut)
@limiter.limit("60/minute")
def login(request: Request, payload: DoctorLogin, db: Session = Depends(get_db)):
    if not verify_captcha_token(payload.captcha_token, payload.captcha_answer):
        raise HTTPException(status_code=400, detail="Incorrect captcha. Please try again.")

    email = payload.email.lower().strip()
    doctor = db.query(Doctor).filter(Doctor.email == email).first()

    if not doctor:
        # Burn the same time a real password check takes, so response time doesn't
        # reveal whether this email has an account.
        verify_password(payload.password, _TIMING_HASH)
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

    # Deactivation is only revealed AFTER the password is proven, so the login form
    # can't be used to find out which emails exist or which accounts are switched off.
    if not doctor.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated. Contact your admin.")
    if doctor.hospital_id and doctor.hospital and not doctor.hospital.is_active:
        raise HTTPException(status_code=403, detail="Your hospital account has been deactivated. Contact support.")

    # Successful login — reset failed attempts
    doctor.failed_login_attempts = 0
    doctor.locked_until = None
    db.commit()

    if doctor.role.value == "super_admin" and not _superadmin_2fa_skipped():
        return StaffLoginResultOut(
            status="totp_required" if doctor.totp_enabled else "totp_setup_required",
            totp_token=create_totp_pending_token(doctor.id),
        )

    if doctor.must_change_password:
        # Correct temp password + correct captcha — but this account still
        # needs to set its own password before it gets a real session.
        return StaffLoginResultOut(
            status="needs_password_change",
            setup_token=create_password_setup_token(doctor.id),
        )

    token = create_access_token({"sub": str(doctor.id), "role": doctor.role.value})
    return StaffLoginResultOut(status="success", access_token=token, doctor=doctor)

def _superadmin_2fa_skipped() -> bool:
    return bool(settings.DEV_SKIP_SUPERADMIN_2FA) and not _is_production(settings)


class TotpSetupIn(BaseModel):
    totp_token: str


class TotpCodeIn(BaseModel):
    totp_token: str
    code: str


def _totp_doctor(db: Session, token: str) -> Doctor:
    doctor_id = verify_totp_pending_token(token)
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first() if doctor_id else None
    if not doctor or doctor.role.value != "super_admin" or not doctor.is_active:
        raise HTTPException(status_code=401, detail="Your sign-in expired. Please sign in again.")
    if doctor.locked_until and now_ist_naive() < doctor.locked_until:
        raise HTTPException(status_code=429, detail="Account temporarily locked. Try again later.")
    return doctor


def _totp_fail(db: Session, doctor: Doctor):
    doctor.failed_login_attempts = (doctor.failed_login_attempts or 0) + 1
    if doctor.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
        doctor.locked_until = now_ist_naive() + timedelta(minutes=LOCKOUT_MINUTES)
    db.commit()
    raise HTTPException(status_code=400, detail="Incorrect code. Please try again.")


def _totp_secret(doctor: Doctor) -> str:
    secret = totp_util.decrypt_secret(doctor.totp_secret_enc)
    if not secret:
        raise HTTPException(status_code=400, detail="Two-factor data could not be read. Ask the platform owner to run the 2FA recovery script.")
    return secret


def _finish_superadmin_login(doctor: Doctor, backup_codes=None) -> StaffLoginResultOut:
    if doctor.must_change_password:
        return StaffLoginResultOut(
            status="needs_password_change",
            setup_token=create_password_setup_token(doctor.id),
            backup_codes=backup_codes,
        )
    token = create_access_token({"sub": str(doctor.id), "role": doctor.role.value})
    return StaffLoginResultOut(status="success", access_token=token, doctor=doctor, backup_codes=backup_codes)


@router.post("/totp/setup")
@limiter.limit("10/minute")
def totp_setup(request: Request, payload: TotpSetupIn, db: Session = Depends(get_db)):
    """One-time setup screen data: a fresh secret + QR. Only while 2FA is not yet enabled."""
    doctor = _totp_doctor(db, payload.totp_token)
    if doctor.totp_enabled:
        raise HTTPException(status_code=400, detail="Two-factor sign-in is already set up for this account.")
    secret = totp_util.generate_secret()
    doctor.totp_secret_enc = totp_util.encrypt_secret(secret)
    db.commit()
    return {"secret": secret, "qr_data_uri": totp_util.qr_data_uri(totp_util.provisioning_uri(secret, doctor.email))}


@router.post("/totp/confirm", response_model=StaffLoginResultOut)
@limiter.limit("10/minute")
def totp_confirm(request: Request, payload: TotpCodeIn, db: Session = Depends(get_db)):
    doctor = _totp_doctor(db, payload.totp_token)
    if doctor.totp_enabled or not doctor.totp_secret_enc:
        raise HTTPException(status_code=400, detail="Start the two-factor setup again.")
    step = totp_util.verify_code(_totp_secret(doctor), payload.code, doctor.totp_last_step)
    if step is None:
        _totp_fail(db, doctor)
    codes, hashes = totp_util.make_backup_codes()
    doctor.totp_enabled = True
    doctor.totp_last_step = step
    doctor.totp_backup_codes = json.dumps(hashes)
    doctor.failed_login_attempts = 0
    doctor.locked_until = None
    db.commit()
    log_action(db, doctor, action="totp_enabled", target_type="doctor", target_id=doctor.id,
               target_label=doctor.email, hospital_id=None)
    return _finish_superadmin_login(doctor, backup_codes=codes)


@router.post("/login/totp", response_model=StaffLoginResultOut)
@limiter.limit("20/minute")
def totp_login(request: Request, payload: TotpCodeIn, db: Session = Depends(get_db)):
    doctor = _totp_doctor(db, payload.totp_token)
    if not doctor.totp_enabled or not doctor.totp_secret_enc:
        raise HTTPException(status_code=400, detail="Two-factor sign-in is not set up. Sign in again to set it up.")
    code = (payload.code or "").strip()
    plain = code.replace(" ", "")
    used_backup = False
    remaining = None
    if len(plain) == 6 and plain.isdigit():
        step = totp_util.verify_code(_totp_secret(doctor), plain, doctor.totp_last_step)
        if step is None:
            _totp_fail(db, doctor)
        doctor.totp_last_step = step
    else:
        remaining = totp_util.consume_backup_code(code, json.loads(doctor.totp_backup_codes or "[]"))
        if remaining is None:
            _totp_fail(db, doctor)
        doctor.totp_backup_codes = json.dumps(remaining)
        used_backup = True
    doctor.failed_login_attempts = 0
    doctor.locked_until = None
    db.commit()
    if used_backup:
        log_action(db, doctor, action="totp_backup_code_used", target_type="doctor", target_id=doctor.id,
                   target_label=doctor.email, details=f"{len(remaining)} backup codes left", hospital_id=None)
    return _finish_superadmin_login(doctor)


@router.post("/set-new-password", response_model=Token)
@limiter.limit("30/minute")
def set_new_password(request: Request, payload: SetNewPasswordIn, db: Session = Depends(get_db)):
    # The captcha was already solved at login; the setup token proves that
    # login succeeded with the temporary password (see login()).
    setup_doctor_id = verify_password_setup_token(payload.setup_token)
    if setup_doctor_id is None:
        raise HTTPException(status_code=400, detail="Your session expired. Please sign in again.")

    email = payload.email.lower().strip()
    doctor = db.query(Doctor).filter(Doctor.email == email).first()
    if not doctor or doctor.id != setup_doctor_id:
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
    doctor.password_changed_at = datetime.utcnow()
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
    # DISABLED until WhatsApp OTP delivery exists (was a fixed "1234" for every
    # account). Same response for every email, so nothing to enumerate. Hospital
    # admins reset staff passwords instead (POST /admin/doctors/{id}/reset-password).
    raise HTTPException(
        status_code=503,
        detail="Self-service password reset is not available yet. Please ask your hospital admin to reset your password."
    )

@router.post("/forgot-password/verify", response_model=ForgotPasswordVerifyOut)
@limiter.limit("5/minute")
def forgot_password_verify(request: Request, payload: ForgotPasswordVerifyIn, db: Session = Depends(get_db)):
    # DISABLED with the request step above (no OTP exists to verify).
    raise HTTPException(status_code=503, detail="Self-service password reset is not available yet.")

@router.post("/reset-password", response_model=Token)
@limiter.limit("5/minute")
def reset_password(request: Request, payload: ResetPasswordIn, db: Session = Depends(get_db)):
    # DISABLED with the request step above. When WhatsApp OTP goes live,
    # restore the reset logic here and set doctor.password_changed_at.
    raise HTTPException(status_code=503, detail="Self-service password reset is not available yet.")

@router.post("/change-password", response_model=Token)
@limiter.limit("10/minute")
def change_password(
    request: Request,
    payload: ChangePasswordIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    # 400 (not 401) for a wrong current password: the frontend treats any 401
    # as "session expired" and signs the user out.
    if not verify_password(payload.old_password, current_doctor.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    check_password_strength(payload.new_password)
    if payload.new_password == payload.old_password:
        raise HTTPException(status_code=400, detail="New password must be different from the current one")

    current_doctor.hashed_password = hash_password(payload.new_password)
    current_doctor.must_change_password = False
    current_doctor.password_changed_at = datetime.utcnow()
    db.commit()
    db.refresh(current_doctor)

    log_action(
        db, current_doctor,
        action="password_changed",
        target_type="doctor",
        target_id=current_doctor.id,
        target_label=f"{current_doctor.title} {current_doctor.name}",
        hospital_id=current_doctor.hospital_id
    )

    # Every older token (including this session's) is now invalid, so hand
    # back a fresh one for the caller to keep using.
    token = create_access_token({"sub": str(current_doctor.id), "role": current_doctor.role.value})
    return {"access_token": token, "token_type": "bearer", "doctor": current_doctor}

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
    phone = normalize_phone(payload.phone)
    if not name or len(name) > 100:
        raise HTTPException(status_code=400, detail="Name is required (100 characters max)")
    if not phone:
        raise HTTPException(status_code=400, detail="Contact number is required")
    if len(phone) != 10 or phone[0] not in "6789":
        raise HTTPException(status_code=400, detail="Enter a valid 10-digit mobile number")
    if current_doctor.hospital_id and db.query(Doctor.id).filter(
        Doctor.hospital_id == current_doctor.hospital_id,
        Doctor.id != current_doctor.id,
        Doctor.phone.like(f"%{phone}"),
    ).first():
        raise HTTPException(status_code=400, detail="Another account at this hospital already uses that phone number")

    _new_reg = (payload.registration_number or "").strip()
    if len(_new_reg) > 50:
        raise HTTPException(status_code=400, detail="Registration number is too long")
    _old_reg = (current_doctor.registration_number or "").strip()
    if current_doctor.role.value == "doctor" and _old_reg and not _new_reg:
        raise HTTPException(status_code=400, detail="Registration number can't be removed once set. It prints on prescriptions.")
    _before = f"name={current_doctor.name!r}, phone={current_doctor.phone!r}, reg={_old_reg!r}"

    current_doctor.name = name
    current_doctor.phone = phone
    current_doctor.registration_number = _new_reg
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
        hospital_id=current_doctor.hospital_id,
        details=f"Before: {_before}. After: name={name!r}, phone={phone!r}, reg={_new_reg!r}"
    )
    return current_doctor

MAX_SESSION_HOURS = 12  # one shift; after this the person signs in again


@router.post("/refresh")
@limiter.limit("30/minute")
def refresh_session(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    """Sliding session: swaps a still-valid token for a fresh 60-minute one.
    The original sign-in time travels with it ("oiat") so a session can never
    be stretched past MAX_SESSION_HOURS."""
    payload = decode_access_token(credentials.credentials) or {}
    started = payload.get("oiat") or payload.get("iat")
    if not started or datetime.utcnow().timestamp() - float(started) > MAX_SESSION_HOURS * 3600:
        raise HTTPException(status_code=401, detail="Session ended. Please sign in again.")
    token = create_access_token({
        "sub": str(current_doctor.id),
        "role": current_doctor.role.value,
        "oiat": int(started),
    })
    return {"access_token": token}


@router.post("/logout")
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    current_doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db)
):
    blacklist_token(credentials.credentials, db)
    return {"message": "Logged out successfully"}