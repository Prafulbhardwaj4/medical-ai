from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import func
from sqlalchemy.orm import Session


from app.database import get_db
from app.config import settings
from app.models.patient import Patient
from app.models.portal import PatientAccount, PatientProfileLink
from app.schemas.portal import LoginIn, CompleteRegisterIn, TokenOut, PatientSessionOut, LoginResultOut, ChangePasswordIn, AddressUpdateIn, PatientAddressIn, PatientAddressOut, ConfirmProfileIn, DeactivateAccountIn
from app.schemas.portal import PortalForgotPasswordRequestIn, PortalForgotPasswordVerifyIn, PortalForgotPasswordVerifyOut, PortalResetPasswordIn
from app.models.portal import PatientAddress
from app.utils.portal_auth import create_portal_access_token, hash_password, verify_password, get_current_patient_account, portal_security
from app.utils.portal_auth import create_patient_password_reset_token, verify_patient_password_reset_token
from app.utils.portal_auth import create_portal_register_token, verify_portal_register_token
from app.utils.portal_otp import generate_otp, hash_otp, deliver_otp, is_temp_password, temp_password_enabled, OTP_TTL_MINUTES
from app.utils.auth import check_password_strength
import hmac
from app.utils.auth import verify_captcha_token, blacklist_token
from app.utils.rate_limit import limiter, FailureThrottle
from app.utils.timezone import now_ist_naive
from app.utils.phone import normalize_phone

router = APIRouter(prefix="/portal/auth", tags=["portal-auth"])

# Portal accounts have no lockout column, so cap wrong-password attempts per
# phone number: 10 failures in 15 minutes -> blocked until the window clears.
_login_throttle = FailureThrottle(max_failures=10, window_seconds=15 * 60)
_otp_throttle = FailureThrottle(max_failures=5, window_seconds=15 * 60)  # wrong OTP guesses per phone


def _patients_for_phone(db: Session, phone: str):
    """Every hospital record whose phone number normalizes to this one. Works on
    SQLite and PostgreSQL (no regex functions)."""
    stripped = func.replace(func.replace(func.replace(Patient.phone, " ", ""), "-", ""), "+", "")
    candidates = db.query(Patient).filter(stripped.like(f"%{phone}")).all()
    return [p for p in candidates if normalize_phone(p.phone) == phone]


def _session_payload(account: PatientAccount) -> PatientSessionOut:
    self_link = next((link for link in account.profiles if link.relation == "self"), None)
    if not self_link:
        # No confirmed "self" profile yet — most likely this phone matched
        # more than one hospital record at registration, so none were
        # auto-tagged (see _link_all_hospital_records). Still show a real
        # name rather than the bare "Patient" fallback: fall back to
        # whichever linked profile is most recent, until the patient
        # confirms one via the pending-profiles flow. linked_at is a
        # nullable column and older rows (linked before some code path
        # started reliably setting it) can be null, so treat null as the
        # oldest possible value rather than letting the comparison crash.
        candidates = [link for link in account.profiles if link.patient]
        self_link = max(candidates, key=lambda link: link.linked_at or datetime.min, default=None)
    name = self_link.patient.name if self_link and self_link.patient else "Patient"
    return PatientSessionOut(role="patient", name=name, phone=account.phone)


def _link_all_hospital_records(db: Session, account: PatientAccount, phone: str) -> None:
    """Called once at registration completion — links every existing Patient
    row under this phone number, across every hospital, into the account.

    CompleteRegisterIn only collects phone + password (no name), so there is
    no reliable signal for which matching Patient row is actually the person
    registering. If exactly one row matches, it's safe to auto-tag it "self"
    (unchanged behaviour). If more than one distinct row matches — whether
    that's two people force-created under a shared number at one hospital, or
    the same number appearing under different names across hospitals — none
    of them get auto-tagged. They're linked as "pending_confirmation" instead
    and stay excluded from the account's medical history until the patient
    explicitly confirms who each one is from inside the portal."""
    patients = _patients_for_phone(db, phone)
    relation = "self" if len(patients) == 1 else "pending_confirmation"
    for p in patients:
        exists = db.query(PatientProfileLink).filter(PatientProfileLink.patient_id == p.id).first()
        if exists:
            continue
        db.add(PatientProfileLink(
            account_id=account.id, patient_id=p.id,
            relation=relation, linked_at=now_ist_naive()
        ))
    db.commit()


@router.post("/login", response_model=LoginResultOut)
@limiter.limit("20/minute")
def login(request: Request, body: LoginIn, db: Session = Depends(get_db)):
    if not verify_captcha_token(body.captcha_token, body.captcha_answer):
        raise HTTPException(status_code=400, detail="Incorrect captcha. Please try again.")
    _phone = normalize_phone(body.phone)
    if _login_throttle.is_blocked(_phone):
        raise HTTPException(status_code=429, detail="Too many failed attempts. Please try again in 15 minutes.")
    account = db.query(PatientAccount).filter(PatientAccount.phone == _phone).first()

    # First login with the temporary password, for a number that is already a
    # patient at some hospital but has no portal account yet: they set their own.
    if not account and temp_password_enabled() and is_temp_password(body.password) and _patients_for_phone(db, _phone):
        _login_throttle.reset(_phone)
        return LoginResultOut(status="needs_registration", registration_token=create_portal_register_token(_phone))

    # Same generic 401 whether the number has no account or the password is wrong.
    if not account or not verify_password(body.password, account.password_hash):
        _login_throttle.record_failure(_phone)
        raise HTTPException(status_code=401, detail="Invalid phone number or password")
    if not account.is_active:
        # They just proved they own the account (correct password + captcha), and
        # self-deactivation is the only way an account gets here - welcome them back
        # instead of leaving the phone number locked forever.
        account.is_active = True
        db.commit()

    _login_throttle.reset(_phone)
    if account.must_change_password:
        # Account was created for them (e.g. by reception) with the temporary password.
        return LoginResultOut(status="needs_registration", registration_token=create_portal_register_token(_phone))
    return LoginResultOut(
        status="success",
        access_token=create_portal_access_token(account.id),
        doctor=_session_payload(account),
    )


@router.post("/register/complete", response_model=TokenOut)
def complete_registration(body: CompleteRegisterIn, db: Session = Depends(get_db)):
    # Needs the registration_token from /login (issued only after the temporary
    # password was proven), so a phone number + password alone creates nothing.
    phone = normalize_phone(body.phone)
    if not phone or verify_portal_register_token(body.registration_token) != phone:
        raise HTTPException(status_code=400, detail="Your sign-in step expired. Please sign in again.")
    check_password_strength(body.new_password)
    if is_temp_password(body.new_password):
        raise HTTPException(status_code=400, detail="Please choose a different password than the temporary one")

    account = db.query(PatientAccount).filter(PatientAccount.phone == phone).first()
    if account:
        if not account.must_change_password:
            raise HTTPException(status_code=400, detail="This number is already registered. Please sign in.")
        account.password_hash = hash_password(body.new_password)
        account.must_change_password = False
        account.password_changed_at = datetime.utcnow()
        account.is_active = True
    else:
        if not _patients_for_phone(db, phone):
            raise HTTPException(status_code=400, detail="No hospital visit is on record for this number.")
        account = PatientAccount(
            phone=phone, password_hash=hash_password(body.new_password),
            password_changed_at=datetime.utcnow(),
        )
        db.add(account)
        db.flush()
    db.commit()
    _link_all_hospital_records(db, account, phone)
    return TokenOut(
        access_token=create_portal_access_token(account.id),
        doctor=_session_payload(account),
    )


@router.patch("/profiles/{link_id}/confirm")
def confirm_profile(
    link_id: int,
    body: ConfirmProfileIn,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    """Patient explicitly confirms who a pending-confirmation record actually
    is, before it counts as their own history or shows up as a labeled family
    profile. Needed whenever more than one Patient row matched the same phone
    number at registration (see _link_all_hospital_records)."""
    link = db.query(PatientProfileLink).filter(
        PatientProfileLink.id == link_id, PatientProfileLink.account_id == account.id
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Profile not found")
    if link.relation != "pending_confirmation":
        raise HTTPException(status_code=400, detail="This profile has already been confirmed")
    if body.relation not in ("self", "family"):
        raise HTTPException(status_code=400, detail="relation must be 'self' or 'family'")

    link.relation = body.relation
    db.commit()
    return {"message": "Profile confirmed", "relation": link.relation}


@router.delete("/profiles/{link_id}")
def reject_profile(
    link_id: int,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    """Patient says a pending-confirmation record isn't theirs at all —
    unlink it for good. Doesn't touch the underlying hospital Patient row,
    only this account's claim on it."""
    link = db.query(PatientProfileLink).filter(
        PatientProfileLink.id == link_id, PatientProfileLink.account_id == account.id,
        PatientProfileLink.relation == "pending_confirmation",
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Pending profile not found")
    db.delete(link)
    db.commit()
    return {"message": "Removed"}


@router.post("/change-password")
def change_password(
    body: ChangePasswordIn,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    # 400, not 401: the frontend signs the user out on any 401.
    if not verify_password(body.old_password, account.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(body.new_password) < 8 or not any(c.isdigit() for c in body.new_password) or not any(c.isupper() for c in body.new_password):
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters, with 1 number and 1 capital letter")
    if body.new_password == body.old_password:
        raise HTTPException(status_code=400, detail="New password must be different from current password")

    account.password_hash = hash_password(body.new_password)
    account.password_changed_at = datetime.utcnow()
    db.commit()
    # Older tokens (including this session's) are now invalid; return a fresh one.
    return TokenOut(
        access_token=create_portal_access_token(account.id),
        doctor=_session_payload(account),
    )


@router.post("/logout")
def portal_logout(
    credentials: HTTPAuthorizationCredentials = Depends(portal_security),
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    blacklist_token(credentials.credentials, db)
    return {"message": "Logged out successfully"}


@router.post("/forgot-password/request")
@limiter.limit("5/minute")
def forgot_password_request(request: Request, body: PortalForgotPasswordRequestIn, db: Session = Depends(get_db)):
    if not verify_captcha_token(body.captcha_token, body.captcha_answer):
        raise HTTPException(status_code=400, detail="Incorrect captcha. Please try again.")
    phone = normalize_phone(body.phone)
    account = db.query(PatientAccount).filter(PatientAccount.phone == phone).first() if phone else None
    if account and account.is_active:
        otp = generate_otp()
        account.reset_otp_hash = hash_otp(account.id, otp)
        account.reset_otp_expires_at = now_ist_naive() + timedelta(minutes=OTP_TTL_MINUTES)
        db.commit()
        deliver_otp(phone, otp)
    # Same answer for every number, so this can't be used to find who has an account.
    return {"message": "If this number is registered, an OTP has been sent to its WhatsApp."}


@router.post("/forgot-password/verify", response_model=PortalForgotPasswordVerifyOut)
@limiter.limit("5/minute")
def forgot_password_verify(request: Request, body: PortalForgotPasswordVerifyIn, db: Session = Depends(get_db)):
    phone = normalize_phone(body.phone)
    if _otp_throttle.is_blocked(phone):
        raise HTTPException(status_code=429, detail="Too many wrong OTP attempts. Please try again in 15 minutes.")
    account = db.query(PatientAccount).filter(PatientAccount.phone == phone).first() if phone else None
    ok = bool(
        account and account.reset_otp_hash and account.reset_otp_expires_at
        and now_ist_naive() < account.reset_otp_expires_at
        and hmac.compare_digest(hash_otp(account.id, (body.otp or "").strip()), account.reset_otp_hash)
    )
    if not ok:
        _otp_throttle.record_failure(phone)
        raise HTTPException(status_code=400, detail="Incorrect or expired OTP")
    account.reset_otp_hash = None      # single use
    account.reset_otp_expires_at = None
    db.commit()
    _otp_throttle.reset(phone)
    # The token's second field carries the account's password-change stamp, so the
    # token stops working the moment the password is changed (one reset per OTP).
    stamp = str(int(account.password_changed_at.timestamp())) if account.password_changed_at else "0"
    return PortalForgotPasswordVerifyOut(reset_token=create_patient_password_reset_token(account.id, stamp))


@router.post("/reset-password", response_model=TokenOut)
@limiter.limit("5/minute")
def reset_password(request: Request, body: PortalResetPasswordIn, db: Session = Depends(get_db)):
    account_id, stamp = verify_patient_password_reset_token(body.reset_token)
    account = db.query(PatientAccount).filter(PatientAccount.id == account_id).first() if account_id else None
    current_stamp = str(int(account.password_changed_at.timestamp())) if account and account.password_changed_at else "0"
    if not account or not account.is_active or stamp != current_stamp:
        raise HTTPException(status_code=400, detail="This reset link has expired. Please start again.")
    check_password_strength(body.new_password)
    if is_temp_password(body.new_password):
        raise HTTPException(status_code=400, detail="Please choose a different password than the temporary one")
    account.password_hash = hash_password(body.new_password)
    account.must_change_password = False
    account.password_changed_at = datetime.utcnow()
    account.reset_otp_hash = None
    account.reset_otp_expires_at = None
    db.commit()
    return TokenOut(
        access_token=create_portal_access_token(account.id),
        doctor=_session_payload(account),
    )


@router.post("/deactivate")
def deactivate_account(
    body: DeactivateAccountIn,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    if not verify_password(body.password, account.password_hash):
        raise HTTPException(status_code=401, detail="Password is incorrect")
    account.is_active = False
    account.password_changed_at = datetime.utcnow()  # every token issued before now is rejected
    db.commit()
    return {"message": "Account deactivated"}


@router.get("/address")
def get_saved_address(
    account: PatientAccount = Depends(get_current_patient_account),
):
    return {"address": account.address}


@router.patch("/address")
def update_saved_address(
    body: AddressUpdateIn,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    address = body.address.strip()
    if len(address) < 5:
        raise HTTPException(status_code=400, detail="Please enter a fuller address")
    account.address = address
    db.commit()
    return {"address": account.address}


@router.get("/addresses", response_model=list[PatientAddressOut])
def list_addresses(
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    rows = db.query(PatientAddress).filter(PatientAddress.account_id == account.id).order_by(PatientAddress.id).all()
    if not rows and account.address:
        # Lazy one-time migration of the old single-address field into the new list,
        # so accounts that saved an address before this feature existed don't lose it.
        row = PatientAddress(account_id=account.id, label="Home", address=account.address, is_default=True)
        db.add(row)
        db.commit()
        db.refresh(row)
        rows = [row]
    return rows


@router.post("/addresses", response_model=PatientAddressOut)
def add_address(
    body: PatientAddressIn,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    address = body.address.strip()
    if len(address) < 5:
        raise HTTPException(status_code=400, detail="Please enter a fuller address")
    existing_count = db.query(PatientAddress).filter(PatientAddress.account_id == account.id).count()
    is_first = existing_count == 0
    row = PatientAddress(account_id=account.id, label=(body.label or "Address").strip() or "Address", address=address, is_default=is_first)
    db.add(row)
    if is_first:
        account.address = address
    db.commit()
    db.refresh(row)
    return row


@router.delete("/addresses/{address_id}")
def delete_address(
    address_id: int,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    row = db.query(PatientAddress).filter(PatientAddress.id == address_id, PatientAddress.account_id == account.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Address not found")
    was_default = row.is_default
    db.delete(row)
    db.commit()
    if was_default:
        next_row = db.query(PatientAddress).filter(PatientAddress.account_id == account.id).order_by(PatientAddress.id).first()
        if next_row:
            next_row.is_default = True
            account.address = next_row.address
        else:
            account.address = None
        db.commit()
    return {"message": "Address deleted"}


@router.patch("/addresses/{address_id}/default")
def set_default_address(
    address_id: int,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    row = db.query(PatientAddress).filter(PatientAddress.id == address_id, PatientAddress.account_id == account.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Address not found")
    db.query(PatientAddress).filter(PatientAddress.account_id == account.id).update({"is_default": False})
    row.is_default = True
    account.address = row.address
    db.commit()
    return {"message": "Default address updated"}