"""Flow-level helpers that put WhatsApp messages in the list when something happens in the app.
The TEXT of every message is written only in services/whatsapp_messages.py; this file decides
WHEN a message is created, for whom, and who may see it."""
import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.services import whatsapp_messages as wa
from app.utils.phone import normalize_phone
from app.utils.timezone import now_ist_naive

logger = logging.getLogger("whatsapp")


def temp_password_expiry():
    """Every temporary password (admin, staff, patient) is valid for 7 days."""
    return now_ist_naive() + timedelta(days=wa.TEMP_PASSWORD_VALID_DAYS)


def _add_account_messages(db: Session, *, kind, recipient_id, name, role, hospital_id, hospital_name,
                          login_id, phone, password, password_visibility, created_by=None):
    """Template 1 (welcome) first, template 2 (temporary password) right after it. Raises SecretKeyMissing."""
    expires = temp_password_expiry()
    common = dict(hospital_id=hospital_id, recipient_kind=kind, recipient_id=recipient_id, recipient_name=name,
                  recipient_role=role, recipient_phone=phone, created_by=created_by)
    wa.enqueue_message(
        db, template_key=wa.T_WELCOME, visibility=wa.VIS_ALL, expires_at=expires,
        text=wa.build_welcome(name=name, role=role, hospital_name=hospital_name, login_id=login_id), **common)
    full, masked = wa.build_temp_password(password)
    wa.enqueue_message(
        db, template_key=wa.T_TEMP_PASSWORD, visibility=password_visibility, secret=True,
        text=full, masked_text=masked, expires_at=expires, **common)


def queue_account_messages(db: Session, **kwargs) -> bool:
    """Adds the welcome + temporary-password messages inside the caller's transaction (caller commits).
    Never breaks the account creation itself: if the encryption key is missing, nothing is added."""
    try:
        with db.begin_nested():
            _add_account_messages(db, **kwargs)
        return True
    except wa.SecretKeyMissing:
        logger.warning("WhatsApp account messages were not created: WHATSAPP_MESSAGES_KEY is missing")
        return False
    except Exception:
        logger.exception("WhatsApp account messages could not be created")
        return False


def queue_staff_account_messages(db: Session, doctor, hospital, temp_password: str, creator=None,
                                 hospital_admin: bool = False) -> bool:
    """New staff account (created by the hospital admin) or new hospital admin (created by the super admin).
    The password message of a HOSPITAL ADMIN is visible only to the super admin; a staff password message
    is visible to that hospital's admin and the super admin."""
    return queue_account_messages(
        db, kind="staff", recipient_id=doctor.id, name=f"{doctor.title or ''} {doctor.name}".strip(),
        role=doctor.role.value, hospital_id=hospital.id, hospital_name=hospital.name, login_id=doctor.email,
        phone=doctor.phone, password=temp_password,
        password_visibility=wa.VIS_SUPER_ONLY if hospital_admin else wa.VIS_ADMIN_SUPER,
        created_by=creator.id if creator else None,
    )


def ensure_patient_portal_account(db: Session, patient, created_by=None):
    """First-ever registration of this mobile number: creates the portal account with a random temporary
    password (valid 7 days) and adds the welcome + temporary-password messages. Returns the account
    (new or existing), or None if the number is not a valid 10-digit mobile number."""
    from app.models.hospital import Hospital
    from app.models.portal import PatientAccount
    from app.utils.auth import generate_temp_password, hash_password

    phone = normalize_phone(patient.phone)
    if len(phone) != 10:
        return None
    account = db.query(PatientAccount).filter(PatientAccount.phone == phone).first()
    if account:
        return account
    password = generate_temp_password()
    account = PatientAccount(
        phone=phone, password_hash=hash_password(password), must_change_password=True,
        temp_password_expires_at=temp_password_expiry(),
    )
    db.add(account)
    db.flush()
    hospital = db.query(Hospital).filter(Hospital.id == patient.hospital_id).first()
    queue_account_messages(
        db, kind="portal_account", recipient_id=account.id, name=patient.name, role="patient",
        hospital_id=patient.hospital_id, hospital_name=hospital.name if hospital else "",
        login_id=phone, phone=phone, password=password, password_visibility=wa.VIS_ALL,
        created_by=created_by,
    )
    return account