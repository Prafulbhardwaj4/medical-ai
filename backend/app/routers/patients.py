from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from datetime import date, datetime, timedelta
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
from app.schemas.patient import PatientCreate, PatientOut, PatientSummary, CheckinCreate, CheckinOut, DoctorLite, NurseNoteCreate, PaymentMethodIn, EmergencyIntakeIn, PatientMergeIn
from sqlalchemy import or_
from app.utils.auth import get_current_doctor, ist_today, ist_day_bounds
from app.utils.timezone import now_ist_naive
from app.utils.audit import log_action
from app.models.attendance import AttendanceRecord
from app.utils.order_lifecycle import is_order_expired
from app.models.medicine_order import MedicineOrder
from app.models.opd_charge import OpdCharge
from app.models.admission import Admission
from app.models.admission_deposit import AdmissionDepositTopupRequest
from app.models.admission_tpa_case import AdmissionTpaCase
from app.models.refund import Refund
from app.models.opd_referral import OpdReferral
from app.models.admission_referral import AdmissionReferral
from app.models.invoice import Invoice
from app.models.feedback import VisitFeedback
from app.models.patient_merge_request import PatientMergeRequest
from app.models.portal import PatientProfileLink, InviteStatus
from app.schemas.patient import MergeRequestIn, MergeConfirmIn

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("/lookup")
def unified_patient_lookup(
    query: str,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """§1 — single reception entry point: search by phone/UID/token and see which
    situations apply to the patient(s) found, instead of hunting across separate screens."""
    q = query.strip()
    if not q:
        return []

    patients_found = {}

    by_phone_uid = db.query(Patient).filter(
        Patient.hospital_id == current_doctor.hospital_id,
        or_(Patient.phone.like(f"%{q}%"), Patient.patient_uid.ilike(f"%{q}%"))
    ).limit(10).all()
    for p in by_phone_uid:
        patients_found[p.id] = p

    by_token = db.query(Checkin).filter(
        Checkin.hospital_id == current_doctor.hospital_id, Checkin.token_number.ilike(f"%{q}%")
    ).order_by(Checkin.created_at.desc()).limit(5).all()
    for c in by_token:
        p = db.query(Patient).filter(Patient.id == c.patient_id).first()
        if p:
            patients_found[p.id] = p

    results = []
    for p in patients_found.values():
        situations = []

        todays_checkin = db.query(Checkin).filter(
            Checkin.patient_id == p.id, Checkin.hospital_id == current_doctor.hospital_id,
            Checkin.visit_date == ist_today()
        ).order_by(Checkin.created_at.desc()).first()
        if todays_checkin and not todays_checkin.is_paid:
            situations.append("pending_opd_payment")

        if db.query(OpdCharge).filter(OpdCharge.patient_id == p.id, OpdCharge.hospital_id == current_doctor.hospital_id, OpdCharge.status == "payment_pending").count():
            situations.append("pending_opd_charges")
        if db.query(TestOrder).filter(TestOrder.patient_id == p.id, TestOrder.hospital_id == current_doctor.hospital_id, TestOrder.status == "payment_pending").count():
            situations.append("pending_test_payment")

        active_admission = db.query(Admission).filter(
            Admission.patient_id == p.id, Admission.hospital_id == current_doctor.hospital_id, Admission.status == "admitted"
        ).first()
        if active_admission:
            situations.append("active_admission")
            if db.query(AdmissionDepositTopupRequest).filter(AdmissionDepositTopupRequest.admission_id == active_admission.id, AdmissionDepositTopupRequest.status == "pending").count():
                situations.append("pending_topup_request")
            if db.query(AdmissionTpaCase).filter(AdmissionTpaCase.admission_id == active_admission.id, AdmissionTpaCase.status.in_(["pending", "query_raised"])).count():
                situations.append("open_tpa_case")

        if db.query(Refund).filter(Refund.patient_id == p.id, Refund.hospital_id == current_doctor.hospital_id, Refund.status == "pending").count():
            situations.append("refund_settling")

        results.append({
            "id": p.id, "name": p.name, "patient_uid": p.patient_uid, "phone": p.phone,
            "situations": situations,
            "active_admission_token": active_admission.public_token if active_admission else None,
        })

    return results

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

def pick_random_nurse(db: Session, hospital_id: int, doctor_id: int = None):
    present_nurse_ids = [
        r[0] for r in db.query(AttendanceRecord.doctor_id).filter(
            AttendanceRecord.hospital_id == hospital_id,
            AttendanceRecord.date == ist_today(),
            AttendanceRecord.status.in_(["present", "on_break"])
        ).all()
    ]
    if not present_nurse_ids:
        return None

    base_query = db.query(Doctor).filter(
        Doctor.hospital_id == hospital_id,
        Doctor.role.in_([UserRole.nurse, UserRole.assistant]),
        Doctor.is_active == True,
        Doctor.id.in_(present_nurse_ids)
    )

    if doctor_id:
        from app.models.attendance_coverage import AttendanceCoverage
        covering_staff_ids = [
            r[0] for r in db.query(AttendanceRecord.doctor_id).join(
                AttendanceCoverage, AttendanceCoverage.attendance_record_id == AttendanceRecord.id
            ).filter(
                AttendanceRecord.hospital_id == hospital_id,
                AttendanceRecord.date == ist_today(),
                AttendanceRecord.status.in_(["present", "on_break"]),
                AttendanceCoverage.doctor_id == doctor_id
            ).all()
        ]
        if covering_staff_ids:
            covering = base_query.filter(Doctor.id.in_(covering_staff_ids)).all()
            if covering:
                return random.choice(covering)
        # No one has explicitly signed up to cover this doctor — fall back to
        # any present nurse/assistant, same as before coverage existed.

    nurses = base_query.all()
    return random.choice(nurses) if nurses else None

def is_doctor_covered_and_present(db: Session, hospital_id: int, doctor_id: int) -> bool:
    """True if at least one nurse/assistant who is explicitly covering this
    doctor is currently Present/On Break — the same coverage data
    pick_random_nurse consults, but without its fallback-to-any-nurse
    behaviour, since this is used purely as a gate (see checkin_patient's
    walk-in flow and /doctor-coverage-status)."""
    from app.models.attendance_coverage import AttendanceCoverage
    covering_staff_ids = [
        r[0] for r in db.query(AttendanceRecord.doctor_id).join(
            AttendanceCoverage, AttendanceCoverage.attendance_record_id == AttendanceRecord.id
        ).filter(
            AttendanceRecord.hospital_id == hospital_id,
            AttendanceRecord.date == ist_today(),
            AttendanceRecord.status.in_(["present", "on_break"]),
            AttendanceCoverage.doctor_id == doctor_id
        ).all()
    ]
    return len(covering_staff_ids) > 0

def _pick_doctor_for_emergency(db: Session, hospital_id: int):
    """Nearest available doctor = present today and least busy right now.
    Falls back to any active doctor at the hospital if nobody's marked present
    (an emergency should never come back empty)."""
    present_ids = [
        r[0] for r in db.query(AttendanceRecord.doctor_id).filter(
            AttendanceRecord.hospital_id == hospital_id,
            AttendanceRecord.date == ist_today(),
            AttendanceRecord.status == "present"
        ).all()
    ]
    base_query = db.query(Doctor).filter(
        Doctor.hospital_id == hospital_id,
        Doctor.role.in_([UserRole.doctor, UserRole.sub_admin]),
        Doctor.is_active == True,
    )
    candidates = base_query.filter(Doctor.id.in_(present_ids)).all() if present_ids else []
    if not candidates:
        candidates = base_query.all()
    if not candidates:
        return None
    today_counts = dict(
        db.query(Checkin.doctor_id, func.count(Checkin.id))
        .filter(Checkin.hospital_id == hospital_id, Checkin.visit_date == ist_today())
        .group_by(Checkin.doctor_id).all()
    )
    candidates.sort(key=lambda d: today_counts.get(d.id, 0))
    return candidates[0]


@router.post("/emergency-intake", status_code=201)
def emergency_intake(
    payload: EmergencyIntakeIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Minimal, instant record for an emergency walk-in — no payment or full
    registration gate, ever. Goes straight to the nearest available doctor.
    Full registration/billing is completed retroactively via the normal
    PUT /patients/{id} once the patient is identified/stabilized."""
    hospital = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()
    hospital_code = hospital.hospital_code if hospital else "GEN"

    doctor = _pick_doctor_for_emergency(db, current_doctor.hospital_id)
    if not doctor:
        raise HTTPException(status_code=400, detail="No doctor available at this hospital right now")

    label = payload.name.strip() if payload.name and payload.name.strip() else (
        f"Unidentified — approx {payload.approx_age or '?'}y, {payload.approx_gender or 'unknown'}"
    )
    gender = (payload.approx_gender or "Other").capitalize()
    if gender not in ["Male", "Female", "Other"]:
        gender = "Other"

    patient = Patient(
        patient_uid=generate_patient_uid(db, current_doctor.hospital_id, hospital_code),
        url_token=generate_url_token(db),
        name=label,
        phone=f"EMRG-{int(now_ist_naive().timestamp())}",
        age=payload.approx_age or 0,
        gender=gender,
        hospital_id=current_doctor.hospital_id,
        created_by=current_doctor.id,
        is_emergency_unverified=True,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)

    token = generate_token_number(db, current_doctor.hospital_id, hospital.hospital_code)
    checkin = Checkin(
        hospital_id=current_doctor.hospital_id,
        patient_id=patient.id,
        token_number=token,
        issue_category="Emergency intake",
        doctor_id=doctor.id,
        created_by=current_doctor.id,
        visit_date=ist_today(),
        is_paid=True,  # no payment gate — billed retroactively once stabilized
        is_emergency=True,
    )
    db.add(checkin)
    db.commit()
    db.refresh(checkin)

    log_action(
        db, current_doctor,
        action="emergency_intake",
        target_type="patient",
        target_id=patient.id,
        target_label=f"{patient.name} ({patient.patient_uid})",
        details=f"Token {token} → {doctor.title} {doctor.name}"
    )

    return {
        "patient_id": patient.id,
        "url_token": patient.url_token,
        "checkin_id": checkin.id,
        "token_number": token,
        "doctor_name": f"{doctor.title} {doctor.name}",
    }


@router.post("/", response_model=PatientOut, status_code=201)
def create_patient(
    payload: PatientCreate,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    hospital = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()
    hospital_code = hospital.hospital_code if hospital else "GEN"

    if not payload.force:
        existing = db.query(Patient).filter(
            Patient.hospital_id == current_doctor.hospital_id,
            Patient.phone == payload.phone
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail={
                "message": f"{existing.name} ({existing.patient_uid}) is already registered with this phone number.",
                "existing_patient": {
                    "id": existing.id,
                    "name": existing.name,
                    "patient_uid": existing.patient_uid,
                    "age": existing.age,
                    "gender": existing.gender,
                    "phone": existing.phone
                }
            })

    patient = Patient(
        patient_uid=generate_patient_uid(db, current_doctor.hospital_id, hospital_code),
        url_token=generate_url_token(db),
        name=payload.name,
        phone=payload.phone,
        age=payload.age,
        blood_group=payload.blood_group,
        gender=payload.gender,
        abha_number=payload.abha_number,
        address=payload.address,
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

    _auto_link_portal_profile(db, patient)
    _auto_complete_matching_appointment(db, patient, current_doctor.hospital_id)

    return patient


def _auto_complete_matching_appointment(db: Session, patient: Patient, hospital_id: int) -> None:
    """If this patient had booked ahead or reserved a queue-from-home slot
    for today at this hospital, generate their real day-of Checkin/token now
    that reception has created their actual Patient record — the same
    conversion the lazy sweep does for already-linked returning patients,
    see utils/portal_checkin.py."""
    from datetime import datetime, timedelta
    from app.models.portal import Appointment, AppointmentStatus, PatientProfileLink
    from app.utils.portal_checkin import convert_appointment_to_checkin

    today_start = datetime.combine(now_ist_naive().date(), datetime.min.time())
    today_end = today_start + timedelta(days=1)

    from app.models.portal import PatientAccount
    from app.utils.phone import normalize_phone
    account = db.query(PatientAccount).filter(PatientAccount.phone == normalize_phone(patient.phone)).first()
    if not account:
        return

    for a in db.query(Appointment).filter(
        Appointment.account_id == account.id,
        Appointment.hospital_id == hospital_id,
        Appointment.status.in_([AppointmentStatus.booked, AppointmentStatus.confirmed]),
        Appointment.payment_status == "paid",
        Appointment.requested_time >= today_start,
        Appointment.requested_time < today_end,
    ).all():
        if not a.profile_link_id:
            link = db.query(PatientProfileLink).filter(PatientProfileLink.patient_id == patient.id).first()
            if link:
                a.profile_link_id = link.id
        # Reception is creating the Patient record right now because this
        # person just walked in — that IS the arrival moment for a
        # genuinely new patient who never got to tap "I've arrived" first.
        if not a.arrived_at:
            a.arrived_at = now_ist_naive()
        convert_appointment_to_checkin(db, a, patient)


def _auto_link_portal_profile(db: Session, patient: Patient) -> None:
    """If this phone number already has a registered Health Portal account,
    link this new hospital record to it automatically — no confirmation
    step right now since there's no messaging channel yet to confirm via.
    Revisit before public launch (shared/family numbers can auto-link)."""
    from app.models.portal import PatientAccount, PatientProfileLink
    from app.utils.phone import normalize_phone

    account = db.query(PatientAccount).filter(PatientAccount.phone == normalize_phone(patient.phone)).first()
    if not account:
        return
    existing_link = db.query(PatientProfileLink).filter(PatientProfileLink.patient_id == patient.id).first()
    if existing_link:
        return
    db.add(PatientProfileLink(
        account_id=account.id, patient_id=patient.id,
        relation="self", linked_at=now_ist_naive()
    ))
    db.commit()

@router.post("/merge")
def merge_duplicate_patients(
    body: PatientMergeIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    """Interim stopgap until ABHA — manually flag two records as the same
    person and merge their clinical history. Requires phone confirmation
    with the patient first (no reliable automatic way to verify identity
    otherwise)."""
    if current_doctor.role.value not in ["receptionist", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    if not body.phone_confirmed:
        raise HTTPException(status_code=400, detail="Please confirm this with the patient by phone before merging")
    if body.primary_patient_id == body.duplicate_patient_id:
        raise HTTPException(status_code=400, detail="Can't merge a record with itself")

    primary = db.query(Patient).filter(
        Patient.id == body.primary_patient_id, Patient.hospital_id == current_doctor.hospital_id
    ).first()
    duplicate = db.query(Patient).filter(
        Patient.id == body.duplicate_patient_id, Patient.hospital_id == current_doctor.hospital_id
    ).first()
    if not primary or not duplicate:
        raise HTTPException(status_code=404, detail="One or both patient records not found at this hospital")
    if primary.merged_into_id or duplicate.merged_into_id:
        raise HTTPException(status_code=400, detail="One of these records has already been merged")

    from app.models.portal import PatientProfileLink
    primary_link = db.query(PatientProfileLink).filter(PatientProfileLink.patient_id == primary.id).first()
    duplicate_link = db.query(PatientProfileLink).filter(PatientProfileLink.patient_id == duplicate.id).first()
    if primary_link and duplicate_link and primary_link.account_id != duplicate_link.account_id:
        raise HTTPException(
            status_code=400,
            detail="Both records are already linked to different portal accounts — this needs manual support review before merging",
        )
    if duplicate_link and not primary_link:
        duplicate_link.patient_id = primary.id

    from app.models.admission import Admission
    from app.models.admission_referral import AdmissionReferral
    from app.models.checkin import Checkin
    from app.models.consultation import Consultation
    from app.models.invoice import Invoice
    from app.models.medicine_order import MedicineOrder
    from app.models.opd_charge import OpdCharge
    from app.models.opd_referral import OpdReferral
    from app.models.refund import Refund
    from app.models.test_order import TestOrder

    for model in (Admission, AdmissionReferral, Checkin, Consultation, Invoice, MedicineOrder, OpdCharge, OpdReferral, Refund, TestOrder):
        db.query(model).filter(model.patient_id == duplicate.id).update({"patient_id": primary.id})

    duplicate.merged_into_id = primary.id
    db.commit()
    return {"message": f"Merged into {primary.name} ({primary.patient_uid})"}


@router.get("/", response_model=List[PatientSummary])
def list_patients(
    search: str = "",
    page: int = 1,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    offset = (page - 1) * limit
    query = db.query(Patient).filter(Patient.hospital_id == current_doctor.hospital_id, Patient.merged_into_id.is_(None), Patient.is_active == True)
    if search:
        query = query.filter(
            Patient.name.ilike(f"%{search}%") |
            Patient.phone.ilike(f"%{search}%") |
            Patient.patient_uid.ilike(f"%{search}%")
        )
    patients = query.order_by(desc(Patient.created_at)).offset(offset).limit(limit).all()

    patient_ids = [p.id for p in patients]

    from app.models.admission import Admission
    admitted_ids = {row[0] for row in db.query(Admission.patient_id).filter(
        Admission.patient_id.in_(patient_ids), Admission.status == "admitted"
    ).all()}

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
            blood_group=p.blood_group,
            gender=p.gender,
            last_visit=last_visit,
            last_token=last_token,
            checked_in_today=checked_in_today,
            currently_admitted=p.id in admitted_ids,
            address=p.address,
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

    today_attendance = {
        r.doctor_id: r for r in db.query(AttendanceRecord).filter(
            AttendanceRecord.hospital_id == current_doctor.hospital_id,
            AttendanceRecord.date == ist_today()
        ).all()
    }
    present_ids = {doc_id for doc_id, r in today_attendance.items() if r.status == "present"}

    result = []
    for d in doctors:
        rec = today_attendance.get(d.id)
        result.append(DoctorLite(
            id=d.id, title=d.title, name=d.name, specialization=d.specialization,
            consultation_fee=d.consultation_fee,
            on_duty_today=d.id in present_ids,
            room_number=d.room_number,
            attendance_status=rec.status if rec else "not_marked",
            doctor_location=rec.doctor_location if rec else None
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
    location_by_doctor = {r.doctor_id: r.doctor_location for r in records}
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
        "status": status_by_doctor.get(d.id, "present"),
        "location": location_by_doctor.get(d.id)
    } for d in doctors]
    random.shuffle(result)
    return result

@router.get("/doctor-coverage-status/{doctor_id}")
def doctor_coverage_status(
    doctor_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Used by reception's walk-in check-in flow to gate the 'Notify Doctor'
    (straight-to-doctor, no nurse) option — only available when nobody
    covering this doctor is currently present."""
    covered = is_doctor_covered_and_present(db, current_doctor.hospital_id, doctor_id)
    return {"covered": covered}

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
        "post_consult_data": json.loads(checkin.post_consult_data) if checkin.post_consult_data else None,
        "post_consult_nurse_name": f"{post_consult_nurse.title} {post_consult_nurse.name}" if post_consult_nurse else None,
        "checkin_id": checkin.id,
        "consultation_fee": checkin.consultation_fee,
        "test_fee": checkin.test_fee,
        "total_fee": (checkin.consultation_fee or 0) + (checkin.test_fee or 0),
        "is_paid": checkin.is_paid,
        "is_consulted": db.query(Consultation).filter(
            Consultation.token_number == checkin.token_number
        ).first() is not None,
        "is_returned": checkin.is_returned
    }

@router.post("/requeue/{checkin_id}")
def requeue_checkin(
    checkin_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    checkin = db.query(Checkin).filter(
        Checkin.id == checkin_id,
        Checkin.hospital_id == current_doctor.hospital_id,
        Checkin.visit_date == ist_today()
    ).first()
    if not checkin:
        raise HTTPException(status_code=404, detail="Check-in not found")

    already_consulted = db.query(Consultation).filter(
        Consultation.token_number == checkin.token_number
    ).first() is not None
    if not already_consulted:
        raise HTTPException(status_code=400, detail="This patient hasn't been consulted yet today")

    checkin.is_returned = True
    checkin.returned_at = now_ist_naive()
    db.commit()

    patient = db.query(Patient).filter(Patient.id == checkin.patient_id).first()
    log_action(
        db, current_doctor,
        action="checkin_requeued",
        target_type="checkin",
        target_id=checkin.id,
        target_label=f"{patient.name} ({patient.patient_uid})" if patient else str(checkin.patient_id),
        details=f"Token {checkin.token_number} sent back to Dr. {(db.query(Doctor).filter(Doctor.id == checkin.doctor_id).first() or Doctor()).name or ''} without new payment"
    )
    return {"status": "returned", "token_number": checkin.token_number}


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

    nurse = pick_random_nurse(db, current_doctor.hospital_id, current_doctor.id)
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

    nurse = pick_random_nurse(db, current_doctor.hospital_id, current_doctor.id)
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

@router.post("/{patient_id}/refer")
def refer_to_doctor(
    patient_id: int,
    payload: NurseNoteCreate,  # reused: .note carries the referral reason
    to_doctor_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """OPD-level referral to another doctor, same visit — separate from the
    IPD-only AdmissionReferral. Creates its own Checkin for the receiving
    doctor (its own token, its own queue slot) so it flows through the exact
    same queue mechanism everything else does, tagged as a referral.

    ASSUMPTION FLAGGED, not silently decided: this referral checkin carries
    consultation_fee=0 / is_paid=True — no new fee, since it's a continuation
    of the same paid OPD visit, not a fresh registration. If your hospitals
    actually want to charge a second consultation fee for a referral, tell me
    and I'll flip this to require payment like a normal checkin does.
    """
    if current_doctor.role.value != "doctor":
        raise HTTPException(status_code=403, detail="Only a doctor can refer a patient")

    patient = db.query(Patient).filter(
        Patient.id == patient_id,
        Patient.hospital_id == current_doctor.hospital_id
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    to_doctor = db.query(Doctor).filter(
        Doctor.id == to_doctor_id,
        Doctor.hospital_id == current_doctor.hospital_id,
        Doctor.role == UserRole.doctor
    ).first()
    if not to_doctor:
        raise HTTPException(status_code=404, detail="Receiving doctor not found")
    if to_doctor.id == current_doctor.id:
        raise HTTPException(status_code=400, detail="Can't refer a patient to yourself")

    origin_checkin = db.query(Checkin).filter(
        Checkin.patient_id == patient_id,
        Checkin.doctor_id == current_doctor.id,
        Checkin.visit_date == ist_today()
    ).order_by(desc(Checkin.created_at)).first()
    if not origin_checkin:
        raise HTTPException(status_code=400, detail="No check-in found for today under you for this patient.")

    hospital = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()
    token = generate_token_number(db, current_doctor.hospital_id, hospital.hospital_code)

    referral_checkin = Checkin(
        hospital_id=current_doctor.hospital_id,
        patient_id=patient.id,
        token_number=token,
        issue_category=origin_checkin.issue_category,
        doctor_id=to_doctor.id,
        created_by=current_doctor.id,
        visit_date=ist_today(),
        consultation_fee=0,
        test_fee=0,
        is_paid=True
    )
    db.add(referral_checkin)
    db.flush()

    referral = OpdReferral(
        hospital_id=current_doctor.hospital_id,
        patient_id=patient.id,
        referring_doctor_id=current_doctor.id,
        referred_to_doctor_id=to_doctor.id,
        checkin_id=referral_checkin.id,
        note=payload.note.strip() or None
    )
    db.add(referral)
    db.commit()

    log_action(
        db, current_doctor,
        action="opd_referral_sent",
        target_type="patient",
        target_id=patient.id,
        target_label=f"{patient.name} ({patient.patient_uid})",
        details=f"Referred to {to_doctor.title} {to_doctor.name}" + (f": {payload.note}" if payload.note else "")
    )

    return {"message": f"Referred to {to_doctor.title} {to_doctor.name}", "token_number": token}

@router.post("/{patient_id}/send-back-vitals")
def send_back_for_vitals(
    patient_id: int,
    payload: NurseNoteCreate,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Mid-consultation recheck request — patient re-enters the SAME nurse
    (checkin.nurse_id is untouched) with priority over fresh vitals-pending
    patients, and the consultation stays open (nothing here confirms it)."""
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

    note = payload.note.strip()
    if not note:
        raise HTTPException(status_code=400, detail="Say what needs to be rechecked.")

    if not checkin.nurse_id:
        checkin.nurse_id = pick_random_nurse(db, current_doctor.hospital_id, current_doctor.id)

    checkin.vitals_status = "sent_back"
    checkin.vitals_recheck_request = note
    db.commit()

    log_action(
        db, current_doctor,
        action="sent_back_for_vitals",
        target_type="patient",
        target_id=patient.id,
        target_label=f"{patient.name} ({patient.patient_uid})",
        details=note
    )

    return {"status": "sent_back"}

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
    patient.address = payload.address
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
        nurse = pick_random_nurse(db, current_doctor.hospital_id, doctor.id)
        if not nurse:
            raise HTTPException(status_code=400, detail="No nurse available at this hospital yet.")
    elif is_doctor_covered_and_present(db, current_doctor.hospital_id, doctor.id):
        # Server-side backstop for the reception "Notify Doctor" gate — a
        # present nurse/assistant is covering this doctor, so walking the
        # patient straight to the doctor isn't allowed even if the frontend
        # check was bypassed.
        raise HTTPException(status_code=400, detail="A nurse/assistant covering this doctor is present — send the patient to them for vitals instead.")

    hospital = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()
    token = generate_token_number(db, current_doctor.hospital_id, hospital.hospital_code)

    consultation_fee = payload.consultation_fee
    if consultation_fee is None:
        consultation_fee = doctor.consultation_fee
    if consultation_fee is None and hospital:
        consultation_fee = hospital.default_consultation_fee

    # generate_token_number's check-then-generate isn't airtight under real
    # concurrency — the DB's unique constraint on token_number is the actual
    # hard backstop. Retry on the IntegrityError it raises rather than
    # letting a genuine race surface as a raw 500.
    max_token_attempts = 5
    for attempt in range(max_token_attempts):
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
        try:
            db.commit()
            break
        except IntegrityError:
            db.rollback()
            if attempt == max_token_attempts - 1:
                raise HTTPException(status_code=500, detail="Could not generate a unique token — please try again")
            token = generate_token_number(db, current_doctor.hospital_id, hospital.hospital_code)
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
    body: PaymentMethodIn,
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
    checkin.payment_method = body.payment_method
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
    checkin.payment_method = None
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
    try:
        from app.utils.portal_checkin import sweep_todays_online_checkins
        sweep_todays_online_checkins(db, current_doctor.hospital_id)
    except Exception:
        db.rollback()

    try:
        from app.routers.lab import _escalate_unacknowledged_critical_results
        _escalate_unacknowledged_critical_results(db, current_doctor.hospital_id)
    except Exception:
        db.rollback()

    checkins = db.query(Checkin).filter(
        Checkin.hospital_id == current_doctor.hospital_id,
        Checkin.doctor_id == current_doctor.id,
        Checkin.visit_date == ist_today(),
        Checkin.is_paid == True
    ).order_by(func.coalesce(Checkin.queue_priority_time, Checkin.created_at).asc()).all()

    patient_ids = [c.patient_id for c in checkins]
    patients = {p.id: p for p in db.query(Patient).filter(Patient.id.in_(patient_ids)).all()}

    token_numbers = [c.token_number for c in checkins]
    confirmed_tokens = set(
        t[0] for t in db.query(Consultation.token_number)
        .filter(Consultation.token_number.in_(token_numbers)).all()
    )

    referrals_by_checkin = {
        r.checkin_id: r for r in db.query(OpdReferral).filter(
            OpdReferral.checkin_id.in_([c.id for c in checkins])
        ).all()
    }
    referring_doctors = {
        d.id: d for d in db.query(Doctor).filter(
            Doctor.id.in_([r.referring_doctor_id for r in referrals_by_checkin.values()])
        ).all()
    }

    result = []
    for c in checkins:
        p = patients.get(c.patient_id)
        if not p:
            continue
        ref = referrals_by_checkin.get(c.id)
        ref_doctor = referring_doctors.get(ref.referring_doctor_id) if ref else None
        result.append({
            "checkin_id": c.id,
            "patient_id": p.id,
            "patient_name": p.name,
            "patient_uid": p.patient_uid,
            "url_token": p.url_token,
            "token_number": c.token_number,
            "issue_category": c.issue_category,
            "created_at": c.created_at.isoformat(),
            "estimated_time": None,
            "status": "returned" if c.is_returned else ("done" if c.token_number in confirmed_tokens else "waiting"),
            "is_emergency": c.is_emergency,
            "is_referral": ref is not None,
            "referral_note": ref.note if ref else None,
            "referred_by_name": f"{ref_doctor.title} {ref_doctor.name}" if ref_doctor else None,
            "source": c.source,
            "booked_time": c.booked_time.isoformat() if c.booked_time else None,
        })

    # Merge in paid portal appointments for today that haven't been checked
    # in yet, so the doctor sees who's expected and roughly when.
    from app.models.portal import Appointment, AppointmentStatus
    today_start = datetime.combine(ist_today(), datetime.min.time())
    today_end = today_start + timedelta(days=1)

    expected = db.query(Appointment).filter(
        Appointment.hospital_id == current_doctor.hospital_id,
        Appointment.doctor_id == current_doctor.id,
        Appointment.payment_status == "paid",
        Appointment.status.in_([AppointmentStatus.booked, AppointmentStatus.confirmed]),
        Appointment.requested_time >= today_start, Appointment.requested_time < today_end,
    ).all()

    for a in expected:
        patient_name = a.profile_link.patient.name if a.profile_link and a.profile_link.patient else "Portal Patient"
        result.append({
            "checkin_id": None,
            "patient_id": None,
            "patient_name": patient_name,
            "patient_uid": None,
            "url_token": None,
            "token_number": None,
            "issue_category": a.notes or "Booked appointment",
            "created_at": a.requested_time.isoformat(),
            "estimated_time": a.requested_time.isoformat(),
            "status": "expected",
            "is_emergency": False
        })

    result.sort(key=lambda r: r.get("estimated_time") or r["created_at"])
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

        opd_charges = db.query(OpdCharge).filter(OpdCharge.checkin_id == c.id).all()
        if opd_charges:
            pending_charges = [ch for ch in opd_charges if ch.status == "payment_pending"]
            buckets["charges"] = {
                "status": "unpaid" if pending_charges else "paid",
                "pending_count": len(pending_charges),
                "pending_total": sum(ch.amount * ch.quantity for ch in pending_charges)
            }

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

    opd_charges = db.query(OpdCharge).filter(
        OpdCharge.patient_id == patient_id,
        OpdCharge.hospital_id == current_doctor.hospital_id,
        OpdCharge.status == "payment_pending"
    ).order_by(OpdCharge.charged_at).all()

    return {
        "lab": [
            {"id": t.id, "test_name": t.test_name, "price": t.price, "created_at": t.created_at.isoformat()}
            for t in lab_pending
        ],
        "charges": [
            {"id": c.id, "description": c.description, "amount": c.amount, "quantity": c.quantity, "created_at": c.charged_at.isoformat()}
            for c in opd_charges
        ],
        "pharmacy": [
            {"medicine_name": m.medicine_name, "status": m.status}
            for m in medicine_orders
        ]
    }


@router.post("/{patient_id}/collect-test-payment-anyday")
def collect_test_payment_anyday(
    patient_id: int,
    body: PaymentMethodIn,
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
        o.payment_method = body.payment_method
        o.queued_at = now
        total += o.price
    db.commit()

    log_action(
        db, current_doctor,
        action="test_fees_collected_anyday",
        target_type="patient",
        target_id=patient_id,
        target_label=f"Rs.{total:.2f} for {len(payable)} tests (late collection)",
        hospital_id=current_doctor.hospital_id
    )
    return {"charged": total, "count": len(payable)}

@router.get("/{patient_id}/pending-opd-charges")
def get_pending_opd_charges(
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

    charges = db.query(OpdCharge).filter(
        OpdCharge.patient_id == patient_id,
        OpdCharge.hospital_id == current_doctor.hospital_id,
        OpdCharge.status == "payment_pending",
        OpdCharge.charged_at >= today_start,
        OpdCharge.charged_at <= today_end
    ).order_by(OpdCharge.charged_at).all()

    return [
        {"id": c.id, "description": c.description, "amount": c.amount, "quantity": c.quantity}
        for c in charges
    ]


@router.post("/{patient_id}/collect-opd-charges")
def collect_opd_charges(
    patient_id: int,
    body: PaymentMethodIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    today_start, today_end = ist_day_bounds()

    charges = db.query(OpdCharge).filter(
        OpdCharge.patient_id == patient_id,
        OpdCharge.hospital_id == current_doctor.hospital_id,
        OpdCharge.status == "payment_pending",
        OpdCharge.charged_at >= today_start,
        OpdCharge.charged_at <= today_end
    ).all()
    if not charges:
        raise HTTPException(status_code=400, detail="No ad-hoc charges pending payment")

    total = 0
    now = now_ist_naive()
    for c in charges:
        c.status = "paid"
        c.paid_at = now
        c.payment_method = body.payment_method
        total += c.amount * c.quantity
    db.commit()

    log_action(
        db, current_doctor,
        action="opd_charges_collected",
        target_type="patient",
        target_id=patient_id,
        target_label=f"Rs.{total:.2f} for {len(charges)} charge(s)",
        hospital_id=current_doctor.hospital_id
    )
    return {"charged": total, "count": len(charges)}


@router.post("/{patient_id}/collect-opd-charges-anyday")
def collect_opd_charges_anyday(
    patient_id: int,
    body: PaymentMethodIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    charges = db.query(OpdCharge).filter(
        OpdCharge.patient_id == patient_id,
        OpdCharge.hospital_id == current_doctor.hospital_id,
        OpdCharge.status == "payment_pending"
    ).all()
    if not charges:
        raise HTTPException(status_code=400, detail="No ad-hoc charges pending payment")

    total = 0
    now = now_ist_naive()
    for c in charges:
        c.status = "paid"
        c.paid_at = now
        c.payment_method = body.payment_method
        total += c.amount * c.quantity
    db.commit()

    log_action(
        db, current_doctor,
        action="opd_charges_collected_anyday",
        target_type="patient",
        target_id=patient_id,
        target_label=f"Rs.{total:.2f} for {len(charges)} charge(s) (late collection)",
        hospital_id=current_doctor.hospital_id
    )
    return {"charged": total, "count": len(charges)}


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
    body: PaymentMethodIn,
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
        o.payment_method = body.payment_method
        o.queued_at = now
        total += o.price

    db.commit()

    log_action(
        db, current_doctor,
        action="test_fees_collected",
        target_type="patient",
        target_id=patient_id,
        target_label=f"Rs.{total:.2f} for {len(orders)} tests",
        hospital_id=current_doctor.hospital_id
    )
    return {"charged": total, "count": len(orders)}


@router.post("/test-orders/{order_id}/mark-paid")
def mark_test_order_paid(
    order_id: int,
    body: PaymentMethodIn,
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
    order.payment_method = body.payment_method
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
        TestOrder.status == "verified_released"
    ).order_by(TestOrder.verified_at.desc()).all()

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


# ---------- Manual duplicate-patient merge tool (interim stopgap) ----------

def _require_reception_staff(current_doctor: Doctor):
    if current_doctor.role.value not in ["receptionist", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")


def _serialize_merge_request(db: Session, r: PatientMergeRequest):
    primary = db.query(Patient).filter(Patient.id == r.primary_patient_id).first()
    duplicate = db.query(Patient).filter(Patient.id == r.duplicate_patient_id).first()
    return {
        "id": r.id, "status": r.status, "reason": r.reason,
        "primary_patient": {"id": primary.id, "name": primary.name, "phone": primary.phone, "patient_uid": primary.patient_uid} if primary else None,
        "duplicate_patient": {"id": duplicate.id, "name": duplicate.name, "phone": duplicate.phone, "patient_uid": duplicate.patient_uid} if duplicate else None,
        "flagged_at": r.flagged_at.isoformat() if r.flagged_at else None,
        "confirmation_note": r.confirmation_note,
        "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
        "merged_at": r.merged_at.isoformat() if r.merged_at else None,
        "unmerged_profile_link_note": r.unmerged_profile_link_note,
    }


@router.post("/merge-requests")
def create_merge_request(body: MergeRequestIn, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    """Flags two patient records as a suspected duplicate. This is just the
    flag — nothing is merged yet. A phone-confirmed identity check
    (confirm_merge_request) and, separately, an admin's explicit execution
    (execute_merge_request) both have to happen first."""
    _require_reception_staff(current_doctor)
    if body.primary_patient_id == body.duplicate_patient_id:
        raise HTTPException(status_code=400, detail="Cannot merge a patient with themselves")
    primary = db.query(Patient).filter(Patient.id == body.primary_patient_id, Patient.hospital_id == current_doctor.hospital_id, Patient.is_active == True).first()
    duplicate = db.query(Patient).filter(Patient.id == body.duplicate_patient_id, Patient.hospital_id == current_doctor.hospital_id, Patient.is_active == True).first()
    if not primary or not duplicate:
        raise HTTPException(status_code=404, detail="One or both patients not found")
    if db.query(Admission).filter(Admission.patient_id.in_([primary.id, duplicate.id]), Admission.status == "admitted").first():
        raise HTTPException(status_code=400, detail="Cannot flag a merge while either patient has an active admission — complete/discharge first")

    req = PatientMergeRequest(
        hospital_id=current_doctor.hospital_id, primary_patient_id=primary.id, duplicate_patient_id=duplicate.id,
        reason=(body.reason or "").strip() or None, flagged_by=current_doctor.id,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    log_action(db, current_doctor, action="patient_merge_flagged", target_type="patient", target_id=primary.id,
               target_label=f"{primary.name} <- {duplicate.name}", details=req.reason or "")
    return _serialize_merge_request(db, req)


@router.get("/merge-requests")
def list_merge_requests(status: Optional[str] = None, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    _require_reception_staff(current_doctor)
    query = db.query(PatientMergeRequest).filter(PatientMergeRequest.hospital_id == current_doctor.hospital_id)
    if status:
        query = query.filter(PatientMergeRequest.status == status)
    reqs = query.order_by(PatientMergeRequest.flagged_at.desc()).all()
    return [_serialize_merge_request(db, r) for r in reqs]


@router.post("/merge-requests/{request_id}/confirm")
def confirm_merge_request(request_id: int, body: MergeConfirmIn, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    """Logs the phone-based confirmation with the patient — required before
    an admin can execute the actual merge."""
    _require_reception_staff(current_doctor)
    if not body.confirmation_note.strip():
        raise HTTPException(status_code=400, detail="A confirmation note is required — describe what was confirmed with the patient by phone")
    req = db.query(PatientMergeRequest).filter(PatientMergeRequest.id == request_id, PatientMergeRequest.hospital_id == current_doctor.hospital_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Merge request not found")
    if req.status != "pending_confirmation":
        raise HTTPException(status_code=400, detail="This request is not awaiting confirmation")
    req.status = "confirmed"
    req.confirmation_note = body.confirmation_note.strip()
    req.confirmed_by = current_doctor.id
    req.confirmed_at = now_ist_naive()
    db.commit()
    return _serialize_merge_request(db, req)


@router.post("/merge-requests/{request_id}/cancel")
def cancel_merge_request(request_id: int, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    _require_reception_staff(current_doctor)
    req = db.query(PatientMergeRequest).filter(PatientMergeRequest.id == request_id, PatientMergeRequest.hospital_id == current_doctor.hospital_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Merge request not found")
    if req.status in ("merged", "cancelled"):
        raise HTTPException(status_code=400, detail="This request is already closed")
    req.status = "cancelled"
    db.commit()
    return _serialize_merge_request(db, req)


@router.post("/merge-requests/{request_id}/execute")
def execute_merge_request(request_id: int, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    """The actual, irreversible merge — restricted to admin/sub_admin even
    though flagging/confirming is open to reception, since this repoints
    history across the whole record. The duplicate is never hard-deleted:
    every table below gets its patient_id repointed to the primary, then
    the duplicate row itself is soft-marked is_active=False with
    merged_into_id set, so it stays in the DB for audit history."""
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Only an admin can execute a patient merge")
    req = db.query(PatientMergeRequest).filter(PatientMergeRequest.id == request_id, PatientMergeRequest.hospital_id == current_doctor.hospital_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Merge request not found")
    if req.status != "confirmed":
        raise HTTPException(status_code=400, detail="This request must be phone-confirmed before it can be executed")

    primary_id, duplicate_id = req.primary_patient_id, req.duplicate_patient_id
    primary = db.query(Patient).filter(Patient.id == primary_id).first()
    duplicate = db.query(Patient).filter(Patient.id == duplicate_id).first()
    if not primary or not duplicate or not primary.is_active or not duplicate.is_active:
        raise HTTPException(status_code=400, detail="One or both patient records are no longer available to merge")
    if db.query(Admission).filter(Admission.patient_id.in_([primary_id, duplicate_id]), Admission.status == "admitted").first():
        raise HTTPException(status_code=400, detail="Cannot execute a merge while either patient has an active admission")

    # Straightforward repoints — no uniqueness constraints on patient_id in any of these.
    for model in (Admission, AdmissionReferral, Checkin, Consultation, VisitFeedback, Invoice, MedicineOrder, OpdCharge, OpdReferral, Refund, TestOrder, InviteStatus):
        db.query(model).filter(model.patient_id == duplicate_id).update({model.patient_id: primary_id}, synchronize_session=False)

    # patient_profile_links has a unique constraint on patient_id — only
    # repoint if the primary doesn't already have its own portal link;
    # otherwise leave it on the now-inactive duplicate and flag it for
    # manual follow-up rather than risk a constraint violation.
    unmerged_note = None
    dup_link = db.query(PatientProfileLink).filter(PatientProfileLink.patient_id == duplicate_id).first()
    if dup_link:
        primary_has_link = db.query(PatientProfileLink).filter(PatientProfileLink.patient_id == primary_id).first()
        if not primary_has_link:
            dup_link.patient_id = primary_id
        else:
            unmerged_note = "Duplicate record had its own linked portal account, which was not carried over since the primary already has one — review manually if needed."

    duplicate.is_active = False
    duplicate.merged_into_id = primary_id
    req.status = "merged"
    req.merged_by = current_doctor.id
    req.merged_at = now_ist_naive()
    req.unmerged_profile_link_note = unmerged_note
    db.commit()

    log_action(db, current_doctor, action="patient_merge_executed", target_type="patient", target_id=primary_id,
               target_label=f"{primary.name} <- {duplicate.name}", details=unmerged_note or "")
    return _serialize_merge_request(db, req)