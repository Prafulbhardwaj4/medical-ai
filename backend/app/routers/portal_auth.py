from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.models.patient import Patient
from app.models.portal import PatientAccount, PatientProfileLink
from app.schemas.portal import LoginIn, CompleteRegisterIn, TokenOut, PatientSessionOut, LoginResultOut, ChangePasswordIn, AddressUpdateIn, PatientAddressIn, PatientAddressOut
from app.models.portal import PatientAddress
from app.utils.portal_auth import create_portal_access_token, hash_password, verify_password, get_current_patient_account
from app.utils.timezone import now_ist_naive
from app.utils.phone import normalize_phone

router = APIRouter(prefix="/portal/auth", tags=["portal-auth"])


def _hospital_record_exists(db: Session, phone: str) -> bool:
    candidates = db.query(Patient).filter(Patient.phone.like(f"%{phone}")).all()
    return any(normalize_phone(p.phone) == phone for p in candidates)


def _session_payload(account: PatientAccount) -> PatientSessionOut:
    first_link = account.profiles[0] if account.profiles else None
    name = first_link.patient.name if first_link and first_link.patient else "Patient"
    return PatientSessionOut(role="patient", name=name, phone=account.phone)


def _link_all_hospital_records(db: Session, account: PatientAccount, phone: str) -> None:
    """Called once at registration completion — links every existing Patient
    row under this phone number, across every hospital, into the account."""
    candidates = db.query(Patient).filter(Patient.phone.like(f"%{phone}")).all()
    patients = [p for p in candidates if normalize_phone(p.phone) == phone]
    for p in patients:
        exists = db.query(PatientProfileLink).filter(PatientProfileLink.patient_id == p.id).first()
        if exists:
            continue
        db.add(PatientProfileLink(
            account_id=account.id, patient_id=p.id,
            relation="self", linked_at=now_ist_naive()
        ))
    db.commit()


@router.post("/login", response_model=LoginResultOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    account = db.query(PatientAccount).filter(PatientAccount.phone == body.phone).first()

    if account:
        if not account.is_active:
            raise HTTPException(status_code=403, detail="This account has been deactivated")
        if not verify_password(body.password, account.password_hash):
            raise HTTPException(status_code=401, detail="Invalid phone number or password")
        return LoginResultOut(
            status="success",
            access_token=create_portal_access_token(account.id),
            doctor=_session_payload(account),
        )

    # No account yet — check if this is a valid first-time login.
    has_hospital_record = _hospital_record_exists(db, body.phone)
    if not has_hospital_record:
        raise HTTPException(status_code=401, detail="No hospital visit found for this number")

    # TEMP, pre-launch only: everyone's first-login password is the same
    # fixed value until real OTP delivery is wired up.
    if body.password != settings.PORTAL_DEFAULT_TEMP_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid phone number or password")

    return LoginResultOut(status="needs_registration")


@router.post("/register/complete", response_model=TokenOut)
def complete_registration(body: CompleteRegisterIn, db: Session = Depends(get_db)):
    if db.query(PatientAccount).filter(PatientAccount.phone == body.phone).first():
        raise HTTPException(status_code=400, detail="An account already exists for this number. Please log in.")

    if not _hospital_record_exists(db, body.phone):
        raise HTTPException(status_code=400, detail="No hospital visit found for this number")

    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if body.new_password == settings.PORTAL_DEFAULT_TEMP_PASSWORD:
        raise HTTPException(status_code=400, detail="Please choose a password different from the temporary one")

    account = PatientAccount(phone=body.phone, password_hash=hash_password(body.new_password))
    db.add(account)
    db.commit()
    db.refresh(account)

    _link_all_hospital_records(db, account, body.phone)
    db.refresh(account)

    return TokenOut(
        access_token=create_portal_access_token(account.id),
        doctor=_session_payload(account),
    )


@router.post("/change-password")
def change_password(
    body: ChangePasswordIn,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    if not verify_password(body.old_password, account.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    if body.new_password == body.old_password:
        raise HTTPException(status_code=400, detail="New password must be different from current password")

    account.password_hash = hash_password(body.new_password)
    db.commit()
    return {"message": "Password changed successfully"}


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