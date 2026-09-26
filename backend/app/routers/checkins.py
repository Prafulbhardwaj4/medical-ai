from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.doctor import Doctor
from app.models.checkin import Checkin
from app.models.patient import Patient
from app.utils.auth import get_current_doctor

router = APIRouter(prefix="/checkins", tags=["checkins"])


@router.get("/{checkin_id}/token-for")
def token_for_checkin(checkin_id: int, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    """Item 2 fix — mirrors admissions.py's token_for_admission, same
    auth/scoping pattern, but resolving a checkin_id (e.g. from an
    emergency_ward_intake notification) to the patient_id + url_token
    dashboard.html's existing goToPatient(id, token) needs. There was no
    prior way to resolve this — /admissions/token-for/{id} is the wrong
    table for a checkin_id."""
    c = db.query(Checkin).filter(Checkin.id == checkin_id, Checkin.hospital_id == current_doctor.hospital_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Checkin not found")
    patient = db.query(Patient).filter(Patient.id == c.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return {"patient_id": patient.id, "token": patient.url_token}