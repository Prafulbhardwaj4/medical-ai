from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import date, datetime
import json

from app.database import get_db
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.consultation import Consultation
from app.utils.auth import get_current_doctor

router = APIRouter(prefix="/pharmacy", tags=["pharmacy"])


def require_pharmacy(current_doctor: Doctor):
    if current_doctor.role.value not in ["pharmacy", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")


@router.get("/queue")
def get_pharmacy_queue(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_pharmacy(current_doctor)

    today_start = datetime.combine(date.today(), datetime.min.time())
    today_end = datetime.combine(date.today(), datetime.max.time())

    rows = (
        db.query(Consultation, Patient)
        .join(Patient, Consultation.patient_id == Patient.id)
        .filter(
            Patient.hospital_id == current_doctor.hospital_id,
            Consultation.token_number != None,
            Consultation.is_voided == False,
            Consultation.created_at >= today_start,
            Consultation.created_at <= today_end
        )
        .order_by(desc(Consultation.created_at))
        .all()
    )

    return [
        {
            "token_number": c.token_number,
            "patient_name": p.name,
            "confirmed_at": c.created_at.isoformat(),
            "is_dispensed": c.is_dispensed,
            "dispensed_at": c.dispensed_at.isoformat() if c.dispensed_at else None,
            "verify_hash": c.verify_hash
        }
        for c, p in rows
    ]


@router.get("/prescription/{token_number}")
def get_pharmacy_prescription(
    token_number: str,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_pharmacy(current_doctor)

    consultation = db.query(Consultation).filter(
        Consultation.token_number == token_number,
        Consultation.is_voided == False
    ).first()
    if not consultation:
        raise HTTPException(status_code=404, detail="Prescription not found")

    patient = db.query(Patient).filter(
        Patient.id == consultation.patient_id,
        Patient.hospital_id == current_doctor.hospital_id
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Prescription not found")

    doctor = db.query(Doctor).filter(Doctor.id == consultation.doctor_id).first()
    medicines = json.loads(consultation.medicines or "[]")

    return {
        "token_number": consultation.token_number,
        "patient_name": patient.name,
        "patient_age": patient.age,
        "patient_gender": patient.gender,
        "doctor_name": f"{doctor.title} {doctor.name}" if doctor else "—",
        "confirmed_at": consultation.created_at.isoformat(),
        "medicines": medicines,
        "is_dispensed": consultation.is_dispensed,
        "dispensed_at": consultation.dispensed_at.isoformat() if consultation.dispensed_at else None,
        "verify_hash": consultation.verify_hash
    }