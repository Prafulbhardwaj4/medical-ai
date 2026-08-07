from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.models.patient import Patient
from app.models.portal import PatientAccount, PatientProfileLink
from app.schemas.portal import LoginIn, CompleteRegisterIn, TokenOut, PatientSessionOut, LoginResultOut, ChangePasswordIn, AddressUpdateIn, PatientAddressIn, PatientAddressOut, ConfirmProfileIn
from app.models.portal import PatientAddress
from app.utils.portal_auth import create_portal_access_token, hash_password, verify_password, get_current_patient_account
from app.utils.timezone import now_ist_naive
from app.utils.phone import normalize_phone

router = APIRouter(prefix="/portal/auth", tags=["portal-auth"])


def _session_payload(account: PatientAccount) -> PatientSessionOut:
    first_link = account.profiles[0] if account.profiles else None
    name = first_link.patient.name if first_link and first_link.patient else "Patient"
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
    candidates = db.query(Patient).filter(Patient.phone.like(f"%{phone}")).all()
    patients = [p for p in candidates if normalize_phone(p.phone) == phone]
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

    # No account yet — could be a brand-new phone number (no hospital visit
    # at all) or a returning patient who hasn't completed registration.
    # Same path either way until real OTP delivery exists: fixed temp
    # password for the first login.
    if body.password != settings.PORTAL_DEFAULT_TEMP_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid phone number or password")

    return LoginResultOut(status="needs_registration")


@router.post("/register/complete", response_model=TokenOut)
def complete_registration(body: CompleteRegisterIn, db: Session = Depends(get_db)):
    if db.query(PatientAccount).filter(PatientAccount.phone == body.phone).first():
        raise HTTPException(status_code=400, detail="An account already exists for this number. Please log in.")

    if len(body.new_password) < 8 or not any(c.isdigit() for c in body.new_password) or not any(c.isupper() for c in body.new_password):
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters, with 1 number and 1 capital letter")
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
    if not verify_password(body.old_password, account.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(body.new_password) < 8 or not any(c.isdigit() for c in body.new_password) or not any(c.isupper() for c in body.new_password):
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters, with 1 number and 1 capital letter")
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