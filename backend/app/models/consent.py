from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.consent_record import ConsentRecord
from app.utils.auth import get_current_doctor
from app.utils.audit import log_action

router = APIRouter(prefix="/consent", tags=["consent"])

# Notice versions are placeholders until a lawyer approves the real wording.
NOTICE_VERSIONS = {
    "ai_recording": "ai_recording-v0-PENDING-LEGAL-REVIEW",
    "hiv_test": "hiv_test-v0-PENDING-LEGAL-REVIEW",
}


class PatientConsentIn(BaseModel):
    purpose: str = Field(..., pattern="^(ai_recording|hiv_test)$")


@router.get("/notice/{purpose}")
def get_notice(purpose: str, current_doctor: Doctor = Depends(get_current_doctor)):
    if purpose not in NOTICE_VERSIONS:
        raise HTTPException(status_code=404, detail="Unknown notice")
    return {
        "purpose": purpose,
        "version": NOTICE_VERSIONS[purpose],
        "text": "PENDING LEGAL REVIEW. The hospital's patient notice for this purpose will appear here.",
    }


@router.post("/patients/{patient_id}")
def record_patient_consent(
    patient_id: int,
    body: PatientConsentIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    """Staff ticks 'patient informed' (e.g. before AI recording). Stores who, when, which notice version."""
    if current_doctor.role.value not in ("doctor", "sub_admin", "admin", "nurse", "receptionist", "assistant"):
        raise HTTPException(status_code=403, detail="Not authorized")
    patient = db.query(Patient).filter(
        Patient.id == patient_id, Patient.hospital_id == current_doctor.hospital_id
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    rec = ConsentRecord(
        hospital_id=current_doctor.hospital_id, subject_type="patient", subject_id=patient.id,
        purpose=body.purpose, notice_version=NOTICE_VERSIONS[body.purpose], recorded_by=current_doctor.id,
    )
    db.add(rec)
    db.commit()
    log_action(
        db, current_doctor, action="consent_recorded", target_type="patient", target_id=patient.id,
        target_label=f"{patient.name} ({patient.patient_uid})",
        details=f"{body.purpose} / {NOTICE_VERSIONS[body.purpose]}", hospital_id=current_doctor.hospital_id,
    )
    return {"recorded": True, "notice_version": rec.notice_version}