from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from typing import List
from app.database import get_db
from app.models.patient import Patient
from app.models.consultation import Consultation
from app.models.doctor import Doctor
from app.models.hospital import Hospital
from app.schemas.patient import PatientCreate, PatientOut, PatientSummary
from app.utils.auth import get_current_doctor

router = APIRouter(prefix="/patients", tags=["patients"])

def generate_patient_uid(db: Session, hospital_id: int, hospital_code: str) -> str:
    from sqlalchemy import text
    prefix = hospital_code.replace("-", "")[:4].upper()
    while True:
        count = db.query(Patient).filter(Patient.hospital_id == hospital_id).count() + 1
        uid = f"{prefix}-{count:04d}"
        existing = db.query(Patient).filter(Patient.patient_uid == uid).first()
        if not existing:
            return uid

@router.post("/", response_model=PatientOut, status_code=201)
def create_patient(
    payload: PatientCreate,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    hospital = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()
    hospital_code = hospital.hospital_code if hospital else "GEN"

    patient = Patient(
        patient_uid=generate_patient_uid(db, current_doctor.hospital_id, hospital_code),
        name=payload.name,
        phone=payload.phone,
        age=payload.age,
        blood_group=payload.blood_group,
        gender=payload.gender,
        hospital_id=current_doctor.hospital_id,
        created_by=current_doctor.id
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient

@router.get("/", response_model=List[PatientSummary])
def list_patients(
    search: str = "",
    page: int = 1,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    offset = (page - 1) * limit
    query = db.query(Patient).filter(Patient.hospital_id == current_doctor.hospital_id)
    if search:
        query = query.filter(
            Patient.name.ilike(f"%{search}%") |
            Patient.phone.ilike(f"%{search}%") |
            Patient.patient_uid.ilike(f"%{search}%")
        )
    patients = query.order_by(desc(Patient.created_at)).offset(offset).limit(limit).all()

    patient_ids = [p.id for p in patients]

    # Single query to get last consultation per patient
    latest_consult_subq = (
        db.query(
            Consultation.patient_id,
            func.max(Consultation.created_at).label("max_created_at")
        )
        .filter(Consultation.patient_id.in_(patient_ids))
        .group_by(Consultation.patient_id)
        .subquery()
    )
    latest_consults = (
        db.query(Consultation)
        .join(
            latest_consult_subq,
            (Consultation.patient_id == latest_consult_subq.c.patient_id) &
            (Consultation.created_at == latest_consult_subq.c.max_created_at)
        )
        .all()
    )
    consult_map = {c.patient_id: c for c in latest_consults}

    result = []
    for p in patients:
        last_consult = consult_map.get(p.id)
        result.append(PatientSummary(
            id=p.id,
            patient_uid=p.patient_uid,
            name=p.name,
            phone=p.phone,
            age=p.age,
            gender=p.gender,
            last_visit=last_consult.created_at if last_consult else None,
            last_token=last_consult.token_number if last_consult else None,
        ))
    return result

@router.get("/{patient_id}", response_model=PatientOut)
def get_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    patient = db.query(Patient).filter(
        Patient.id == patient_id,
        Patient.hospital_id == current_doctor.hospital_id
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient

@router.put("/{patient_id}", response_model=PatientOut)
def update_patient(
    patient_id: int,
    payload: PatientCreate,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    patient = db.query(Patient).filter(
        Patient.id == patient_id,
        Patient.hospital_id == current_doctor.hospital_id
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    patient.name = payload.name
    patient.phone = payload.phone
    patient.age = payload.age
    patient.blood_group = payload.blood_group
    patient.gender = payload.gender
    db.commit()
    db.refresh(patient)
    return patient