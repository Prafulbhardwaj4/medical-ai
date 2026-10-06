"""Consent capture mechanisms (Phase C).

Mechanism only. The notice TEXT is placeholder and marked PENDING LEGAL REVIEW in the
pages; bump NOTICE_VERSION whenever the approved wording changes so patients are asked again.
"""
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.consent_record import ConsentRecord
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.portal import PatientAccount
from app.utils.audit import log_action
from app.utils.auth import get_current_doctor
from app.utils.roles import require_super_admin
from app.utils.portal_auth import get_current_patient_account
from app.utils.timezone import ist_day_bounds, now_ist_naive

router = APIRouter(tags=["consents"])

NOTICE_VERSION = "v0-PENDING-LEGAL-REVIEW"
STAFF_CONSENT_PURPOSES = {"ai_recording"}
PORTAL_PURPOSES = ("terms", "privacy")
DATA_REQUEST_KINDS = {"export", "correction", "erasure"}
RECORDING_ROLES = ("doctor", "sub_admin", "admin")


class PatientConsentIn(BaseModel):
    purpose: str = Field(max_length=40)


class DataRequestIn(BaseModel):
    kind: str = Field(max_length=20)
    note: Optional[str] = Field(default=None, max_length=500)


# ---------------------------------------------------------------- staff side

@router.post("/consent/patients/{patient_id}")
def record_patient_consent(
    patient_id: int,
    body: PatientConsentIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    """The doctor confirms the patient was told the consultation is recorded and AI-processed."""
    if current_doctor.role.value not in RECORDING_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized for this action")
    if body.purpose not in STAFF_CONSENT_PURPOSES:
        raise HTTPException(status_code=400, detail="Unknown consent purpose")

    patient = db.query(Patient).filter(
        Patient.id == patient_id, Patient.hospital_id == current_doctor.hospital_id
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    day_start, day_end = ist_day_bounds()
    already = db.query(ConsentRecord.id).filter(
        ConsentRecord.subject_type == "patient",
        ConsentRecord.subject_id == patient.id,
        ConsentRecord.purpose == body.purpose,
        ConsentRecord.notice_version == NOTICE_VERSION,
        ConsentRecord.created_at >= day_start, ConsentRecord.created_at < day_end,
    ).first()
    if already:
        return {"recorded": True, "notice_version": NOTICE_VERSION}

    db.add(ConsentRecord(
        hospital_id=current_doctor.hospital_id,
        subject_type="patient", subject_id=patient.id,
        purpose=body.purpose, notice_version=NOTICE_VERSION,
        recorded_by=current_doctor.id,
    ))
    db.commit()
    log_action(
        db, current_doctor, action="consent_recorded", target_type="patient",
        target_id=patient.id, target_label=f"{patient.name} ({patient.patient_uid})",
        details=f"{body.purpose}, notice {NOTICE_VERSION}", hospital_id=current_doctor.hospital_id,
    )
    return {"recorded": True, "notice_version": NOTICE_VERSION}


# --------------------------------------------------------------- portal side

@router.get("/portal/auth/consent-status")
def portal_consent_status(
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    done = {
        r[0] for r in db.query(ConsentRecord.purpose).filter(
            ConsentRecord.subject_type == "portal_account",
            ConsentRecord.subject_id == account.id,
            ConsentRecord.notice_version == NOTICE_VERSION,
            ConsentRecord.purpose.in_(PORTAL_PURPOSES),
        ).all()
    }
    return {"accepted": all(p in done for p in PORTAL_PURPOSES), "notice_version": NOTICE_VERSION}


@router.post("/portal/auth/consent")
def portal_accept_terms(
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    existing = {
        r[0] for r in db.query(ConsentRecord.purpose).filter(
            ConsentRecord.subject_type == "portal_account",
            ConsentRecord.subject_id == account.id,
            ConsentRecord.notice_version == NOTICE_VERSION,
            ConsentRecord.purpose.in_(PORTAL_PURPOSES),
        ).all()
    }
    for purpose in PORTAL_PURPOSES:
        if purpose not in existing:
            db.add(ConsentRecord(
                hospital_id=None, subject_type="portal_account", subject_id=account.id,
                purpose=purpose, notice_version=NOTICE_VERSION,
            ))
    db.commit()
    return {"accepted": True, "notice_version": NOTICE_VERSION}


@router.post("/portal/auth/data-request")
def portal_data_request(
    body: DataRequestIn,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    """Logs a patient's export / correction / erasure request for the platform team to action.
    Stored in consent_records (purpose data_request_<kind>) so no new table is needed."""
    kind = body.kind.strip().lower()
    if kind not in DATA_REQUEST_KINDS:
        raise HTTPException(status_code=400, detail="kind must be export, correction or erasure")

    purpose = f"data_request_{kind}"
    recent = db.query(ConsentRecord.id).filter(
        ConsentRecord.subject_type == "portal_account",
        ConsentRecord.subject_id == account.id,
        ConsentRecord.purpose == purpose,
        ConsentRecord.created_at >= now_ist_naive() - timedelta(hours=24),
    ).count()
    if recent >= 1:
        raise HTTPException(status_code=429, detail="You already sent this request today. We will contact you.")

    db.add(ConsentRecord(
        hospital_id=None, subject_type="portal_account", subject_id=account.id,
        purpose=purpose, notice_version="requested",
    ))
    db.commit()
    return {"message": "Request received. The MedScribe team will contact you on your registered phone number."}


# ---------------------------------------------------------------- super admin

@router.get("/admin/data-requests")
def list_data_requests(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(require_super_admin),
):
    rows = db.query(ConsentRecord, PatientAccount).join(
        PatientAccount, PatientAccount.id == ConsentRecord.subject_id
    ).filter(
        ConsentRecord.subject_type == "portal_account",
        ConsentRecord.purpose.like("data_request_%"),
    ).order_by(ConsentRecord.created_at.desc()).limit(200).all()
    return [
        {
            "id": c.id,
            "kind": c.purpose.replace("data_request_", ""),
            "phone": a.phone,
            "requested_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c, a in rows
    ]