from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from typing import List, Optional
from datetime import date, datetime
import json
import random
from app.database import get_db
from app.models.patient import Patient
from app.models.consultation import Consultation
from app.models.doctor import Doctor, UserRole
from app.models.hospital import Hospital
from app.models.checkin import Checkin
from app.models.test_catalog import TestCatalogItem
from app.models.test_order import TestOrder
from app.models.checkin import Checkin
import os
from app.schemas.patient import PatientCreate, PatientOut, PatientSummary, CheckinCreate, CheckinOut, DoctorLite, NurseNoteCreate
from sqlalchemy import or_
from app.utils.auth import get_current_doctor, ist_today, ist_day_bounds
from app.utils.timezone import now_ist_naive
from app.utils.audit import log_action
from app.models.attendance import AttendanceRecord
from app.utils.order_lifecycle import is_order_expired
from app.models.medicine_order import MedicineOrder

router = APIRouter(prefix="/patients", tags=["patients"])

def generate_patient_uid(db: Session, hospital_id: int, hospital_code: str) -> str:
    import secrets, string
    prefix = hospital_code.replace("-", "")[:4].upper()
    alphabet = string.ascii_uppercase + string.digits
    while True:
        suffix = "".join(secrets.choice(alphabet) for _ in range(6))
        uid = f"{prefix}-{suffix}"
        existing = db.query(Patient).filter(Patient.patient_uid == uid).first()
        if not existing:
            return uid

def generate_url_token(db: Session) -> str:
    import secrets
    while True:
        token = secrets.token_urlsafe(9)
        existing = db.query(Patient).filter(Patient.url_token == token).first()
        if not existing:
            return token

def pick_random_nurse(db: Session, hospital_id: int):
    present_nurse_ids = [
        r[0] for r in db.query(AttendanceRecord.doctor_id).filter(
            AttendanceRecord.hospital_id == hospital_id,
            AttendanceRecord.date == ist_today(),
            AttendanceRecord.status.in_(["present", "on_break"])
        ).all()
    ]
    if not present_nurse_ids:
        return None
    nurses = db.query(Doctor).filter(
        Doctor.hospital_id == hospital_id,
        Doctor.role == UserRole.nurse,
        Doctor.is_active == True,
        Doctor.id.in_(present_nurse_ids)
    ).all()
    return random.choice(nurses) if nurses else None

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
        url_token=generate_url_token(db),
        name=payload.name,
        phone=payload.phone,
        age=payload.age,
        blood_group=payload.blood_group,
        gender=payload.gender,
        abha_number=payload.abha_number,
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

        checked_in_today = bool(last_checkin and last_checkin.visit_date == ist_today())

        result.append(PatientSummary(
            id=p.id,
            patient_uid=p.patient_uid,
            url_token=p.url_token,
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
    from app.models.attendance import AttendanceRecord
    doctors = db.query(Doctor).filter(
        Doctor.hospital_id == current_doctor.hospital_id,
        Doctor.role.in_([UserRole.doctor, UserRole.sub_admin]),
        Doctor.is_active == True
    ).all()

    present_ids = set(
        r[0] for r in db.query(AttendanceRecord.doctor_id).filter(
            AttendanceRecord.hospital_id == current_doctor.hospital_id,
            AttendanceRecord.date == ist_today(),
            AttendanceRecord.status == "present"
        ).all()
    )

    result = []
    for d in doctors:
        result.append(DoctorLite(
            id=d.id, title=d.title, name=d.name, specialization=d.specialization,
            consultation_fee=d.consultation_fee,
            on_duty_today=d.id in present_ids,
            room_number=d.room_number
        ))
    return result

@router.get("/doctors-in-room/{room_id}")
def doctors_in_room(
    room_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    from app.models.room import Room
    room = db.query(Room).filter(
        Room.id == room_id,
        Room.hospital_id == current_doctor.hospital_id,
        Room.is_active == True
    ).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    records = db.query(AttendanceRecord).filter(
        AttendanceRecord.hospital_id == current_doctor.hospital_id,
        AttendanceRecord.date == ist_today(),
        AttendanceRecord.room_id == room_id,
        AttendanceRecord.status.in_(["present", "on_break"])
    ).all()
    status_by_doctor = {r.doctor_id: r.status for r in records}
    if not status_by_doctor:
        return []

    doctors = db.query(Doctor).filter(
        Doctor.id.in_(status_by_doctor.keys()),
        Doctor.hospital_id == current_doctor.hospital_id,
        Doctor.role.in_([UserRole.doctor, UserRole.sub_admin]),
        Doctor.is_active == True
    ).all()

    result = [{
        "id": d.id,
        "title": d.title,
        "name": d.name,
        "specialization": d.specialization,
        "consultation_fee": d.consultation_fee,
        "status": status_by_doctor.get(d.id, "present")
    } for d in doctors]
    random.shuffle(result)
    return result

@router.get("/hospital-nurses")
def hospital_nurses(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    nurses = db.query(Doctor).filter(
        Doctor.hospital_id == current_doctor.hospital_id,
        Doctor.role == UserRole.nurse,
        Doctor.is_active == True
    ).all()
    return [{"id": n.id, "name": n.name} for n in nurses]

@router.get("/resolve/{token}")
def resolve_patient_token(
    token: str,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    patient = db.query(Patient).filter(
        Patient.url_token == token,
        Patient.hospital_id == current_doctor.hospital_id
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return {"id": patient.id, "url_token": patient.url_token}

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
        Checkin.visit_date == ist_today()
    ).order_by(desc(Checkin.created_at)).first()

    if not checkin:
        return {"exists": False}

    doctor = db.query(Doctor).filter(Doctor.id == checkin.doctor_id).first()

    if checkin.vitals_status == "done" and checkin.vitals_recorded_by:
        attending_nurse = db.query(Doctor).filter(Doctor.id == checkin.vitals_recorded_by).first()
    else:
        attending_nurse = db.query(Doctor).filter(Doctor.id == checkin.nurse_id).first() if checkin.nurse_id else None

    if checkin.post_consult_status == "done" and checkin.post_consult_recorded_by:
        post_consult_nurse = db.query(Doctor).filter(Doctor.id == checkin.post_consult_recorded_by).first()
    else:
        post_consult_nurse = db.query(Doctor).filter(Doctor.id == checkin.nurse_id).first() if checkin.nurse_id else None

    return {
        "exists": True,
        "token_number": checkin.token_number,
        "patient_name": patient.name,
        "doctor_name": f"{doctor.title} {doctor.name}" if doctor else "—",
        "issue_category": checkin.issue_category,
        "visit_date": checkin.visit_date.isoformat(),
        "vitals_status": checkin.vitals_status,
        "vitals_data": json.loads(checkin.vitals_data) if checkin.vitals_data else None,
        "nurse_name": f"{attending_nurse.title} {attending_nurse.name}" if attending_nurse else None,
        "post_consult_status": checkin.post_consult_status,
        "post_consult_note": checkin.post_consult_note,
        "post_consult_nurse_name": f"{post_consult_nurse.title} {post_consult_nurse.name}" if post_consult_nurse else None,
        "checkin_id": checkin.id,
        "consultation_fee": checkin.consultation_fee,
        "test_fee": checkin.test_fee,
        "total_fee": (checkin.consultation_fee or 0) + (checkin.test_fee or 0),
        "is_paid": checkin.is_paid
    }

@router.get("/checkins/{checkin_id}/slip")
def get_checkin_slip(
    checkin_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    checkin = db.query(Checkin).filter(
        Checkin.id == checkin_id,
        Checkin.hospital_id == current_doctor.hospital_id
    ).first()
    if not checkin:
        raise HTTPException(status_code=404, detail="Visit not found")

    patient = db.query(Patient).filter(Patient.id == checkin.patient_id).first()
    doctor = db.query(Doctor).filter(Doctor.id == checkin.doctor_id).first()

    if checkin.vitals_status == "done" and checkin.vitals_recorded_by:
        attending_nurse = db.query(Doctor).filter(Doctor.id == checkin.vitals_recorded_by).first()
    else:
        attending_nurse = db.query(Doctor).filter(Doctor.id == checkin.nurse_id).first() if checkin.nurse_id else None

    return {
        "token_number": checkin.token_number,
        "patient_name": patient.name if patient else "—",
        "doctor_name": f"{doctor.title} {doctor.name}" if doctor else "—",
        "issue_category": checkin.issue_category,
        "visit_date": checkin.visit_date.isoformat(),
        "nurse_name": f"{attending_nurse.title} {attending_nurse.name}" if attending_nurse else None,
        "checkin_id": checkin.id,
        "total_fee": (checkin.consultation_fee or 0) + (checkin.test_fee or 0),
        "is_paid": checkin.is_paid
    }

@router.post("/{patient_id}/send-to-nurse")
def send_to_nurse(
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
        Checkin.visit_date == ist_today()
    ).order_by(desc(Checkin.created_at)).first()
    if not checkin:
        raise HTTPException(status_code=400, detail="No check-in found for today.")

    nurse = pick_random_nurse(db, current_doctor.hospital_id)
    if not nurse:
        raise HTTPException(status_code=400, detail="No nurse available at this hospital yet.")

    checkin.nurse_id = nurse.id
    checkin.vitals_status = "pending"
    db.commit()

    log_action(
        db, current_doctor,
        action="sent_to_nurse_vitals",
        target_type="patient",
        target_id=patient.id,
        target_label=f"{patient.name} ({patient.patient_uid})",
        details=f"Assigned to {nurse.title} {nurse.name}"
    )

    return {"nurse_name": f"{nurse.title} {nurse.name}"}

@router.post("/{patient_id}/send-to-nurse-postconsult")
def send_to_nurse_postconsult(
    patient_id: int,
    payload: NurseNoteCreate,
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
        Checkin.visit_date == ist_today()
    ).order_by(desc(Checkin.created_at)).first()
    if not checkin:
        raise HTTPException(status_code=400, detail="No check-in found for today.")

    nurse = pick_random_nurse(db, current_doctor.hospital_id)
    if not nurse:
        raise HTTPException(status_code=400, detail="No nurse available at this hospital yet.")

    checkin.nurse_id = nurse.id
    checkin.post_consult_status = "pending"
    checkin.post_consult_note = payload.note
    db.commit()

    log_action(
        db, current_doctor,
        action="sent_to_nurse_postconsult",
        target_type="patient",
        target_id=patient.id,
        target_label=f"{patient.name} ({patient.patient_uid})",
        details=f"{payload.note} → {nurse.title} {nurse.name}"
    )

    return {"nurse_name": f"{nurse.title} {nurse.name}"}

# Must stay registered before /{patient_id} below — that route is a 1-segment int path param
# and, being registered first, was silently swallowing every request to this literal path
# ("hospital-tests" failing int conversion, hence the 422s). Any other new literal 1-segment
# GET route added to this router needs to go above /{patient_id} too, for the same reason.
@router.get("/hospital-tests")
def get_hospital_tests(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    items = db.query(TestCatalogItem).filter(
        TestCatalogItem.hospital_id == current_doctor.hospital_id,
        TestCatalogItem.is_active == True
    ).order_by(TestCatalogItem.name).all()
    return [
        {"id": t.id, "test_name": t.name, "price": t.fee, "aliases": t.aliases or ""}
        for t in items
    ]

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
    patient.abha_number = payload.abha_number
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
    today = ist_today()
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
        Doctor.role.in_([UserRole.doctor, UserRole.sub_admin])
    ).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    nurse = None
    if payload.send_to_nurse:
        nurse = pick_random_nurse(db, current_doctor.hospital_id)
        if not nurse:
            raise HTTPException(status_code=400, detail="No nurse available at this hospital yet.")

    hospital = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()
    token = generate_token_number(db, current_doctor.hospital_id, hospital.hospital_code)

    consultation_fee = payload.consultation_fee
    if consultation_fee is None:
        consultation_fee = doctor.consultation_fee
    if consultation_fee is None and hospital:
        consultation_fee = hospital.default_consultation_fee

    checkin = Checkin(
        hospital_id=current_doctor.hospital_id,
        patient_id=patient.id,
        token_number=token,
        issue_category=payload.issue_category,
        doctor_id=doctor.id,
        created_by=current_doctor.id,
        visit_date=ist_today(),
        nurse_id=nurse.id if nurse else None,
        vitals_status="pending" if nurse else "none",
        consultation_fee=consultation_fee,
        test_fee=payload.test_fee
    )
    db.add(checkin)
    db.commit()
    db.refresh(checkin)

    log_action(
        db, current_doctor,
        action="patient_checked_in",
        target_type="patient",
        target_id=patient.id,
        target_label=f"{patient.name} ({patient.patient_uid})",
        details=f"Token {token} → {doctor.title} {doctor.name} ({payload.issue_category})" + (f" · sent to {nurse.title} {nurse.name} for vitals" if nurse else "")
    )

    return CheckinOut(
        checkin_id=checkin.id,
        token_number=token,
        patient_name=patient.name,
        doctor_name=f"{doctor.title} {doctor.name}",
        issue_category=payload.issue_category,
        visit_date=ist_today(),
        nurse_name=f"{nurse.title} {nurse.name}" if nurse else None,
        consultation_fee=consultation_fee,
        test_fee=payload.test_fee,
        total_fee=(consultation_fee or 0) + (payload.test_fee or 0),
        is_paid=False
    )

@router.patch("/checkin/{checkin_id}/mark-paid")
def mark_checkin_paid(
    checkin_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    checkin = db.query(Checkin).filter(
        Checkin.id == checkin_id,
        Checkin.hospital_id == current_doctor.hospital_id
    ).first()
    if not checkin:
        raise HTTPException(status_code=404, detail="Check-in not found")

    checkin.is_paid = True
    checkin.paid_at = now_ist_naive()
    db.commit()

    patient = db.query(Patient).filter(Patient.id == checkin.patient_id).first()
    log_action(
        db, current_doctor,
        action="payment_collected",
        target_type="patient",
        target_id=checkin.patient_id,
        target_label=f"{patient.name} ({patient.patient_uid})" if patient else str(checkin.patient_id),
        details=f"Token {checkin.token_number} · Rs.{(checkin.consultation_fee or 0) + (checkin.test_fee or 0):.2f}"
    )
    return {"is_paid": True, "paid_at": checkin.paid_at.isoformat()}


@router.patch("/checkin/{checkin_id}/mark-unpaid")
def mark_checkin_unpaid(
    checkin_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    checkin = db.query(Checkin).filter(
        Checkin.id == checkin_id,
        Checkin.hospital_id == current_doctor.hospital_id
    ).first()
    if not checkin:
        raise HTTPException(status_code=404, detail="Check-in not found")

    checkin.is_paid = False
    checkin.paid_at = None
    if checkin.is_finalized:
        checkin.is_finalized = False
        checkin.invoice_id = None
    db.commit()

    patient = db.query(Patient).filter(Patient.id == checkin.patient_id).first()
    log_action(
        db, current_doctor,
        action="payment_reverted",
        target_type="patient",
        target_id=checkin.patient_id,
        target_label=f"{patient.name} ({patient.patient_uid})" if patient else str(checkin.patient_id),
        details=f"Token {checkin.token_number} — consultation fee marked unpaid"
    )
    return {"is_paid": False}


@router.post("/{patient_id}/revert-test-payment")
def revert_test_payment(
    patient_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    todays_checkin = db.query(Checkin).filter(
        Checkin.patient_id == patient_id,
        Checkin.hospital_id == current_doctor.hospital_id,
        Checkin.visit_date == ist_today()
    ).order_by(desc(Checkin.created_at)).first()
    if not todays_checkin:
        raise HTTPException(status_code=404, detail="No visit found for today")

    consultation_ids = [
        c.id for c in db.query(Consultation).filter(
            Consultation.patient_id == patient_id,
            or_(
                Consultation.token_number == todays_checkin.token_number,
                Consultation.token_number.like(f"{todays_checkin.token_number}-%")
            )
        ).all()
    ]

    orders = db.query(TestOrder).filter(
        TestOrder.patient_id == patient_id,
        TestOrder.hospital_id == current_doctor.hospital_id,
        TestOrder.consultation_id.in_(consultation_ids),
        TestOrder.status == "paid"
    ).all()

    if not orders:
        raise HTTPException(status_code=400, detail="No paid tests to revert for today's visit — they may already be in progress at the lab")

    for o in orders:
        o.status = "payment_pending"
        o.paid_at = None
        o.queued_at = None

    if todays_checkin.is_finalized:
        todays_checkin.is_finalized = False
        todays_checkin.invoice_id = None

    db.commit()

    log_action(
        db, current_doctor,
        action="test_payment_reverted",
        target_type="patient",
        target_id=patient_id,
        target_label=f"{len(orders)} test(s) reverted to unpaid"
    )
    return {"reverted": len(orders)}

@router.get("/queue/today")
def todays_queue(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    checkins = db.query(Checkin).filter(
        Checkin.hospital_id == current_doctor.hospital_id,
        Checkin.doctor_id == current_doctor.id,
        Checkin.visit_date == ist_today(),
        Checkin.is_paid == True
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
            "url_token": p.url_token,
            "token_number": c.token_number,
            "issue_category": c.issue_category,
            "created_at": c.created_at.isoformat(),
            "status": "done" if c.token_number in confirmed_tokens else "waiting"
        })
    return result


@router.get("/reception/pending-payments")
def reception_pending_payments(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Ambient box on the receptionist main screen — today's check-ins only,
    with per-patient Consultation / Tests / Pharmacy buckets. A bucket is
    omitted entirely if it doesn't apply to that patient."""
    if current_doctor.role.value not in ["receptionist", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    today = ist_today()
    day_start, day_end = ist_day_bounds(today)

    checkins = db.query(Checkin).filter(
        Checkin.hospital_id == current_doctor.hospital_id,
        Checkin.visit_date == today
    ).order_by(Checkin.created_at.asc()).all()

    result = []
    for c in checkins:
        patient = db.query(Patient).filter(Patient.id == c.patient_id).first()
        if not patient:
            continue

        consultations = db.query(Consultation).filter(
            Consultation.patient_id == c.patient_id,
            Consultation.created_at >= day_start,
            Consultation.created_at <= day_end
        ).all()
        consultation_ids = [cc.id for cc in consultations]

        buckets = {}

        if c.consultation_fee is not None:
            buckets["consultation"] = {"status": "paid" if c.is_paid else "unpaid"}

        if consultation_ids:
            test_orders = db.query(TestOrder).filter(
                TestOrder.consultation_id.in_(consultation_ids),
                TestOrder.included == True
            ).all()
            if test_orders:
                pending = [t for t in test_orders if t.status == "payment_pending"]
                buckets["tests"] = {
                    "status": "unpaid" if pending else "paid",
                    "pending_count": len(pending),
                    "pending_total": sum(t.price for t in pending)
                }

            medicine_orders = db.query(MedicineOrder).filter(
                MedicineOrder.consultation_id.in_(consultation_ids),
                MedicineOrder.included == True
            ).all()
            if medicine_orders:
                statuses = set(m.status for m in medicine_orders)
                if "advised" in statuses:
                    pharm_status = "pending"
                elif "paid" in statuses:
                    pharm_status = "paid_not_dispensed"
                else:
                    pharm_status = "dispensed"
                buckets["pharmacy"] = {"status": pharm_status}

        if not buckets:
            continue

        result.append({
            "checkin_id": c.id,
            "patient_id": patient.id,
            "patient_name": patient.name,
            "patient_uid": patient.patient_uid,
            "patient_phone": patient.phone,
            "buckets": buckets
        })

    return result


@router.get("/{patient_id}/pending-tasks")
def get_patient_pending_tasks(
    patient_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Search-based modal (not the same-day ambient box) — for a patient who
    never paid on consultation day. Shows lab tests still payable (any day,
    within window) and pharmacy status read-only (pharmacy always collects
    its own money)."""
    patient = db.query(Patient).filter(
        Patient.id == patient_id,
        Patient.hospital_id == current_doctor.hospital_id
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    test_orders = db.query(TestOrder).filter(
        TestOrder.patient_id == patient_id,
        TestOrder.hospital_id == current_doctor.hospital_id,
        TestOrder.status == "payment_pending",
        TestOrder.included == True
    ).all()
    lab_pending = [
        t for t in test_orders
        if not is_order_expired(db, patient_id, t.consultation_id, t.created_at)
    ]

    medicine_orders = db.query(MedicineOrder).filter(
        MedicineOrder.patient_id == patient_id,
        MedicineOrder.hospital_id == current_doctor.hospital_id
    ).order_by(MedicineOrder.created_at.desc()).limit(15).all()

    return {
        "lab": [
            {"id": t.id, "test_name": t.test_name, "price": t.price, "created_at": t.created_at.isoformat()}
            for t in lab_pending
        ],
        "pharmacy": [
            {"medicine_name": m.medicine_name, "status": m.status}
            for m in medicine_orders
        ]
    }


@router.post("/{patient_id}/collect-test-payment-anyday")
def collect_test_payment_anyday(
    patient_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Used from the search-based pending-tasks modal — collects payment for
    included, non-expired payment_pending tests regardless of what day they
    were ordered on."""
    orders = db.query(TestOrder).filter(
        TestOrder.patient_id == patient_id,
        TestOrder.hospital_id == current_doctor.hospital_id,
        TestOrder.status == "payment_pending",
        TestOrder.included == True
    ).all()

    payable = [o for o in orders if not is_order_expired(db, patient_id, o.consultation_id, o.created_at)]
    if not payable:
        raise HTTPException(status_code=400, detail="No payable tests pending — window may have closed")

    total = 0
    now = now_ist_naive()
    for o in payable:
        o.status = "paid"
        o.paid_at = now
        o.queued_at = now
        total += o.price
    db.commit()

    log_action(
        db, current_doctor,
        action="test_fees_collected_anyday",
        target_type="patient",
        target_id=patient_id,
        target_label=f"Rs.{total} for {len(payable)} tests (late collection)",
        hospital_id=current_doctor.hospital_id
    )
    return {"charged": total, "count": len(payable)}

@router.get("/{patient_id}/pending-test-fees")
def get_pending_test_fees(
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

    today_start, today_end = ist_day_bounds()

    orders = db.query(TestOrder).filter(
        TestOrder.patient_id == patient_id,
        TestOrder.hospital_id == current_doctor.hospital_id,
        TestOrder.status == "payment_pending",
        TestOrder.created_at >= today_start,
        TestOrder.created_at <= today_end
    ).order_by(TestOrder.created_at).all()

    return [
        {"id": o.id, "test_name": o.test_name, "price": o.price, "status": o.status, "included": o.included}
        for o in orders
    ]


@router.patch("/test-orders/{order_id}/toggle-include")
def toggle_test_order_include(
    order_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    order = db.query(TestOrder).filter(
        TestOrder.id == order_id,
        TestOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Test order not found")
    if order.status != "payment_pending":
        raise HTTPException(status_code=400, detail="Cannot change inclusion after payment")

    order.included = not order.included
    db.commit()
    return {"id": order.id, "included": order.included}


@router.post("/{patient_id}/collect-test-payment")
def collect_test_payment(
    patient_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    today_start, today_end = ist_day_bounds()

    voided_consultation_ids = [
        c.id for c in db.query(Consultation).filter(
            Consultation.patient_id == patient_id,
            Consultation.is_voided == True
        ).all()
    ]

    orders = db.query(TestOrder).filter(
        TestOrder.patient_id == patient_id,
        TestOrder.hospital_id == current_doctor.hospital_id,
        TestOrder.status == "payment_pending",
        TestOrder.included == True,
        TestOrder.created_at >= today_start,
        TestOrder.created_at <= today_end,
        ~TestOrder.consultation_id.in_(voided_consultation_ids) if voided_consultation_ids else True
    ).all()

    if not orders:
        raise HTTPException(status_code=400, detail="No included tests pending payment")

    total = 0
    now = now_ist_naive()
    for o in orders:
        o.status = "paid"
        o.paid_at = now
        o.queued_at = now
        total += o.price

    db.commit()

    log_action(
        db, current_doctor,
        action="test_fees_collected",
        target_type="patient",
        target_id=patient_id,
        target_label=f"Rs.{total} for {len(orders)} tests",
        hospital_id=current_doctor.hospital_id
    )
    return {"charged": total, "count": len(orders)}


@router.post("/test-orders/{order_id}/mark-paid")
def mark_test_order_paid(
    order_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    order = db.query(TestOrder).filter(
        TestOrder.id == order_id,
        TestOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Test order not found")

    if order.status != "payment_pending":
        raise HTTPException(status_code=400, detail="Test order is not pending payment")

    if is_order_expired(db, order.patient_id, order.consultation_id, order.created_at):
        raise HTTPException(status_code=400, detail="This test order has expired and can no longer be paid for")

    order.status = "paid"
    order.paid_at = now_ist_naive()
    order.queued_at = order.paid_at
    db.commit()

    log_action(
        db, current_doctor,
        action="test_fee_paid",
        target_type="test_order",
        target_id=order.id,
        target_label=order.test_name,
        hospital_id=current_doctor.hospital_id
    )

    return {"id": order.id, "status": order.status, "paid_at": order.paid_at.isoformat()}

@router.get("/{patient_id}/test-orders")
def get_patient_test_orders(
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

    orders = db.query(TestOrder).filter(
        TestOrder.patient_id == patient_id,
        TestOrder.hospital_id == current_doctor.hospital_id
    ).all()

    return [
        {
            "id": o.id,
            "consultation_id": o.consultation_id,
            "test_name": o.test_name,
            "status": o.status
        }
        for o in orders
    ]

@router.get("/checkin-by-token/{token_number}")
def get_checkin_by_token(
    token_number: str,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    checkin = db.query(Checkin).filter(
        Checkin.token_number == token_number,
        Checkin.hospital_id == current_doctor.hospital_id
    ).first()
    if not checkin:
        raise HTTPException(status_code=404, detail="Visit not found for this token")
    return {"checkin_id": checkin.id}

@router.get("/{patient_id}/documents")
def get_patient_documents(
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

    documents = []

    checkins = db.query(Checkin).filter(
        Checkin.patient_id == patient_id,
        Checkin.hospital_id == current_doctor.hospital_id
    ).order_by(Checkin.created_at.desc()).all()

    for c in checkins:
        documents.append({
            "type": "token_slip",
            "label": f"Token Slip — {c.token_number}",
            "ref_id": c.id,
            "extra": c.token_number,
            "date": c.created_at.isoformat() if c.created_at else None,
            "checkin_id": c.id,
            "has_invoice": bool(c.invoice_id)
        })
        if c.invoice_id:
            documents.append({
                "type": "invoice",
                "label": f"Invoice — Token {c.token_number}",
                "ref_id": c.invoice_id,
                "extra": None,
                "date": c.created_at.isoformat() if c.created_at else None
            })

    consultations = db.query(Consultation).filter(
        Consultation.patient_id == patient_id,
        Consultation.pdf_path != None,
        Consultation.is_voided == False
    ).order_by(Consultation.created_at.desc()).all()

    for c in consultations:
        documents.append({
            "type": "prescription",
            "label": f"Prescription — {c.token_number or 'Draft'}",
            "ref_id": c.id,
            "extra": None,
            "date": c.created_at.isoformat() if c.created_at else None
        })

    test_orders = db.query(TestOrder).filter(
        TestOrder.patient_id == patient_id,
        TestOrder.hospital_id == current_doctor.hospital_id,
        TestOrder.status == "completed"
    ).order_by(TestOrder.completed_at.desc()).all()

    grouped_by_consultation = {}
    for t in test_orders:
        grouped_by_consultation.setdefault(t.consultation_id, []).append(t)

    for consultation_id, orders in grouped_by_consultation.items():
        orders_sorted = sorted(orders, key=lambda o: o.id)
        latest_date = max((o.completed_at for o in orders if o.completed_at), default=None)
        test_names = ", ".join(o.test_name for o in orders_sorted)
        documents.append({
            "type": "test_report",
            "label": f"Test Report — {test_names}",
            "ref_id": orders_sorted[0].id,
            "order_ids": [o.id for o in orders_sorted],
            "extra": None,
            "date": latest_date.isoformat() if latest_date else None
        })

    documents.sort(key=lambda d: d["date"] or "", reverse=True)
    return documents


@router.get("/prescriptions/{consultation_id}/download")
def download_prescription_staff(
    consultation_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    consultation = db.query(Consultation).filter(Consultation.id == consultation_id).first()
    if not consultation:
        raise HTTPException(status_code=404, detail="Prescription not found")

    patient = db.query(Patient).filter(
        Patient.id == consultation.patient_id,
        Patient.hospital_id == current_doctor.hospital_id
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Prescription not found")

    doctor = db.query(Doctor).filter(Doctor.id == consultation.doctor_id).first()

    from app.services.pdf_service import generate_prescription_pdf
    pdf_path = generate_prescription_pdf(
        doctor, patient, consultation,
        consultation.token_number or f"consult-{consultation.id}",
        consultation.verify_hash or ""
    )
    consultation.pdf_path = pdf_path
    db.commit()

    from fastapi.responses import FileResponse
    return FileResponse(pdf_path, media_type="application/pdf", filename=os.path.basename(pdf_path))