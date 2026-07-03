from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from typing import List
from datetime import date
from app.database import get_db
from app.models.patient import Patient
from app.models.consultation import Consultation
from app.models.doctor import Doctor
from app.models.hospital import Hospital
from app.models.checkin import Checkin
from app.schemas.patient import PatientCreate, PatientOut, PatientSummary, CheckinCreate, CheckinOut, DoctorLite
from app.utils.auth import get_current_doctor
from app.utils.audit import log_action

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

    log_action(
        db, current_doctor,
        action="patient_created",
        target_type="patient",
        target_id=patient.id,
        target_label=f"{patient.name} ({patient.patient_uid})"
    )

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

    latest_checkin_subq = (
        db.query(
            Checkin.patient_id,
            func.max(Checkin.created_at).label("max_created_at")
        )
        .filter(Checkin.patient_id.in_(patient_ids))
        .group_by(Checkin.patient_id)
        .subquery()
    )
    latest_checkins = (
        db.query(Checkin)
        .join(
            latest_checkin_subq,
            (Checkin.patient_id == latest_checkin_subq.c.patient_id) &
            (Checkin.created_at == latest_checkin_subq.c.max_created_at)
        )
        .all()
    )
    checkin_map = {c.patient_id: c for c in latest_checkins}

    result = []
    for p in patients:
        last_consult = consult_map.get(p.id)
        last_checkin = checkin_map.get(p.id)

        candidates = []
        if last_consult:
            candidates.append((last_consult.created_at, last_consult.token_number))
        if last_checkin:
            candidates.append((last_checkin.created_at, last_checkin.token_number))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            last_visit, last_token = candidates[0]
        else:
            last_visit, last_token = None, None

        checked_in_today = bool(last_checkin and last_checkin.visit_date == date.today())

        result.append(PatientSummary(
            id=p.id,
            patient_uid=p.patient_uid,
            name=p.name,
            phone=p.phone,
            age=p.age,
            gender=p.gender,
            last_visit=last_visit,
            last_token=last_token,
            checked_in_today=checked_in_today,
        ))
    return result

@router.get("/hospital-doctors", response_model=List[DoctorLite])
def hospital_doctors(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    return db.query(Doctor).filter(
        Doctor.hospital_id == current_doctor.hospital_id,
        Doctor.role.in_(["doctor", "sub_admin"]),
        Doctor.is_active == True
    ).all()

@router.get("/{patient_id}/preferred-doctor")
def preferred_doctor(
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

    result = (
        db.query(Consultation.doctor_id, func.count(Consultation.id).label("visit_count"))
        .filter(Consultation.patient_id == patient_id, Consultation.is_voided == False)
        .group_by(Consultation.doctor_id)
        .order_by(desc("visit_count"))
        .first()
    )
    return {"doctor_id": result.doctor_id if result else None}

@router.get("/{patient_id}/checkin-today")
def checkin_today(
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

    checkin = db.query(Checkin).filter(
        Checkin.patient_id == patient_id,
        Checkin.visit_date == date.today()
    ).order_by(desc(Checkin.created_at)).first()

    if not checkin:
        return {"exists": False}

    doctor = db.query(Doctor).filter(Doctor.id == checkin.doctor_id).first()
    return {
        "exists": True,
        "token_number": checkin.token_number,
        "patient_name": patient.name,
        "doctor_name": f"{doctor.title} {doctor.name}" if doctor else "—",
        "issue_category": checkin.issue_category,
        "visit_date": checkin.visit_date.isoformat()
    }

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

    log_action(
        db, current_doctor,
        action="patient_updated",
        target_type="patient",
        target_id=patient.id,
        target_label=f"{patient.name} ({patient.patient_uid})"
    )

    return patient

def generate_token_number(db: Session, hospital_id: int, hospital_code: str) -> str:
    today = date.today()
    prefix = hospital_code.replace("-", "")[:4].upper()
    date_part = today.strftime("%d%m%y")
    while True:
        count = db.query(Checkin).filter(
            Checkin.hospital_id == hospital_id,
            Checkin.visit_date == today
        ).count() + 1
        token = f"{prefix}-{date_part}-{count:03d}"
        existing = db.query(Checkin).filter(Checkin.token_number == token).first()
        if not existing:
            return token

@router.post("/{patient_id}/checkin", response_model=CheckinOut, status_code=201)
def checkin_patient(
    patient_id: int,
    payload: CheckinCreate,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    patient = db.query(Patient).filter(
        Patient.id == patient_id,
        Patient.hospital_id == current_doctor.hospital_id
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    doctor = db.query(Doctor).filter(
        Doctor.id == payload.doctor_id,
        Doctor.hospital_id == current_doctor.hospital_id,
        Doctor.role.in_(["doctor", "sub_admin"])
    ).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    hospital = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()
    token = generate_token_number(db, current_doctor.hospital_id, hospital.hospital_code)

    checkin = Checkin(
        hospital_id=current_doctor.hospital_id,
        patient_id=patient.id,
        token_number=token,
        issue_category=payload.issue_category,
        doctor_id=doctor.id,
        created_by=current_doctor.id,
        visit_date=date.today()
    )
    db.add(checkin)
    db.commit()

    log_action(
        db, current_doctor,
        action="patient_checked_in",
        target_type="patient",
        target_id=patient.id,
        target_label=f"{patient.name} ({patient.patient_uid})",
        details=f"Token {token} → {doctor.title} {doctor.name} ({payload.issue_category})"
    )

    return CheckinOut(
        token_number=token,
        patient_name=patient.name,
        doctor_name=f"{doctor.title} {doctor.name}",
        issue_category=payload.issue_category,
        visit_date=date.today()
    )

@router.get("/queue/today")
def todays_queue(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    checkins = db.query(Checkin).filter(
        Checkin.hospital_id == current_doctor.hospital_id,
        Checkin.doctor_id == current_doctor.id,
        Checkin.visit_date == date.today()
    ).order_by(Checkin.created_at.asc()).all()

    patient_ids = [c.patient_id for c in checkins]
    patients = {p.id: p for p in db.query(Patient).filter(Patient.id.in_(patient_ids)).all()}

    token_numbers = [c.token_number for c in checkins]
    confirmed_tokens = set(
        t[0] for t in db.query(Consultation.token_number)
        .filter(Consultation.token_number.in_(token_numbers)).all()
    )

    result = []
    for c in checkins:
        p = patients.get(c.patient_id)
        if not p:
            continue
        result.append({
            "checkin_id": c.id,
            "patient_id": p.id,
            "patient_name": p.name,
            "patient_uid": p.patient_uid,
            "token_number": c.token_number,
            "issue_category": c.issue_category,
            "created_at": c.created_at.isoformat(),
            "status": "done" if c.token_number in confirmed_tokens else "waiting"
        })
    return result