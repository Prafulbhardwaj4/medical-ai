from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, datetime
import json

from app.database import get_db
from app.models.checkin import Checkin
from app.models.patient import Patient
from app.models.doctor import Doctor
from app.schemas.patient import VitalsSubmit, NurseTaskComplete, AddOpdChargeIn
from app.models.opd_charge import OpdCharge
from app.utils.auth import get_current_doctor, ist_today
from app.utils.timezone import now_ist_naive
from app.utils.audit import log_action

router = APIRouter(prefix="/nurses", tags=["nurses"])

def _require_nurse(current_doctor: Doctor):
    if current_doctor.role.value not in ("nurse", "assistant"):
        raise HTTPException(status_code=403, detail="Not authorized")

def _require_nurse_only(current_doctor: Doctor):
    # Recording a vitals reading is a nurse-only clinical action. Assistant
    # can view vitals status/queue (see vitals_queue below) but must never
    # submit a reading — that scope creep is what this guards against.
    if current_doctor.role.value != "nurse":
        raise HTTPException(status_code=403, detail="Not authorized")

@router.get("/vitals-queue")
def vitals_queue(
    include_done: bool = False,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    _require_nurse(current_doctor)

    from app.utils.portal_checkin import sweep_todays_online_checkins
    sweep_todays_online_checkins(db, current_doctor.hospital_id)

    statuses = ["pending", "sent_back", "done", "none"] if include_done else ["pending", "sent_back", "none"]
    checkins = db.query(Checkin).filter(
        Checkin.hospital_id == current_doctor.hospital_id,
        Checkin.vitals_status.in_(statuses),
        Checkin.visit_date == ist_today(),
        Checkin.is_paid == True,
        Checkin.is_returned == False
    ).order_by(func.coalesce(Checkin.queue_priority_time, Checkin.created_at).asc()).all()

    # Rechecks jump the fresh-vitals-pending line — the doctor's already mid-turn
    # waiting on this, unlike a walk-in still working through the normal queue.
    checkins.sort(key=lambda c: 0 if c.vitals_status == "sent_back" else 1)

    consulted_tokens = set()
    if include_done and checkins:
        from app.models.consultation import Consultation
        consulted_tokens = {
            t[0] for t in db.query(Consultation.token_number).filter(
                Consultation.token_number.in_([c.token_number for c in checkins])
            ).all()
        }

    patients = {p.id: p for p in db.query(Patient).filter(Patient.id.in_([c.patient_id for c in checkins])).all()}
    doctors = {d.id: d for d in db.query(Doctor).filter(Doctor.id.in_([c.doctor_id for c in checkins])).all()}

    result = []
    for c in checkins:
        p = patients.get(c.patient_id)
        if not p:
            continue
        d = doctors.get(c.doctor_id)
        result.append({
            "checkin_id": c.id,
            "patient_id": p.id,
            "patient_name": p.name,
            "patient_uid": p.patient_uid,
            "phone": p.phone,
            "age": p.age,
            "gender": p.gender,
            "token_number": c.token_number,
            "issue_category": c.issue_category,
            "doctor_id": d.id if d else None,
            "doctor_name": f"{d.title} {d.name}" if d else "—",
            "created_at": c.created_at.isoformat(),
            "is_recheck": c.vitals_status == "sent_back",
            "recheck_request": c.vitals_recheck_request,
            "source": c.source,
            "booked_time": c.booked_time.isoformat() if c.booked_time else None,
            "vitals_status": c.vitals_status,
            "is_emergency": c.is_emergency,
            "is_consulted": c.token_number in consulted_tokens,
        })
    return result

@router.post("/vitals/{checkin_id}")
def submit_vitals(
    checkin_id: int,
    payload: VitalsSubmit,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    _require_nurse_only(current_doctor)
    from app.routers.attendance import require_present
    require_present(db, current_doctor)

    checkin = db.query(Checkin).filter(
        Checkin.id == checkin_id,
        Checkin.hospital_id == current_doctor.hospital_id
    ).first()
    if not checkin:
        raise HTTPException(status_code=404, detail="Check-in not found")

    data = {k.strip(): v.strip() for k, v in payload.data.items() if k.strip() and v.strip()}
    if not data:
        raise HTTPException(status_code=400, detail="At least one vitals field is required")

    was_recheck = checkin.vitals_status == "sent_back"

    # Merge, don't overwrite — a recheck usually only touches one vital (e.g. BP),
    # and the rest of that vitals set already recorded earlier shouldn't be wiped.
    existing = {}
    if checkin.vitals_data:
        try:
            existing = json.loads(checkin.vitals_data)
        except Exception:
            existing = {}
    existing.update(data)

    checkin.vitals_data = json.dumps(existing)
    checkin.vitals_status = "done"
    checkin.vitals_recorded_by = current_doctor.id
    checkin.vitals_recorded_at = now_ist_naive()
    checkin.vitals_recheck_request = None
    db.commit()

    patient = db.query(Patient).filter(Patient.id == checkin.patient_id).first()
    log_action(
        db, current_doctor,
        action="vitals_rechecked" if was_recheck else "vitals_recorded",
        target_type="patient",
        target_id=checkin.patient_id,
        target_label=f"{patient.name} ({patient.patient_uid})" if patient else str(checkin.patient_id),
        details=f"Token {checkin.token_number}"
    )
    return {"status": "done"}

@router.get("/history")
def nurse_history(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    _require_nurse(current_doctor)
    from sqlalchemy import or_, and_

    checkins = db.query(Checkin).filter(
        Checkin.hospital_id == current_doctor.hospital_id,
        Checkin.visit_date == ist_today(),
        or_(
            and_(Checkin.vitals_recorded_by == current_doctor.id, Checkin.vitals_status == "done"),
            and_(Checkin.post_consult_recorded_by == current_doctor.id, Checkin.post_consult_status == "done")
        )
    ).all()

    patients = {p.id: p for p in db.query(Patient).filter(Patient.id.in_([c.patient_id for c in checkins])).all()}

    result = []
    for c in checkins:
        p = patients.get(c.patient_id)
        if not p:
            continue
        if c.vitals_recorded_by == current_doctor.id and c.vitals_status == "done":
            result.append({
                "checkin_id": c.id,
                "type": "vitals",
                "patient_name": p.name,
                "patient_uid": p.patient_uid,
                "token_number": c.token_number,
                "data": json.loads(c.vitals_data) if c.vitals_data else {},
                "recorded_at": c.vitals_recorded_at.isoformat() if c.vitals_recorded_at else None
            })
        if c.post_consult_recorded_by == current_doctor.id and c.post_consult_status == "done":
            result.append({
                "checkin_id": c.id,
                "type": "post_consult",
                "patient_name": p.name,
                "patient_uid": p.patient_uid,
                "token_number": c.token_number,
                "data": json.loads(c.post_consult_data) if c.post_consult_data else {},
                "recorded_at": c.post_consult_recorded_at.isoformat() if c.post_consult_recorded_at else None
            })

    result.sort(key=lambda r: r["recorded_at"] or "", reverse=True)
    return result

@router.get("/post-consult-queue")
def post_consult_queue(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    _require_nurse(current_doctor)
    checkins = db.query(Checkin).filter(
        Checkin.hospital_id == current_doctor.hospital_id,
        Checkin.post_consult_status == "pending",
        Checkin.visit_date == ist_today()
    ).order_by(Checkin.created_at.asc()).all()

    patients = {p.id: p for p in db.query(Patient).filter(Patient.id.in_([c.patient_id for c in checkins])).all()}
    doctors = {d.id: d for d in db.query(Doctor).filter(Doctor.id.in_([c.doctor_id for c in checkins])).all()}

    result = []
    for c in checkins:
        p = patients.get(c.patient_id)
        if not p:
            continue
        d = doctors.get(c.doctor_id)
        result.append({
            "checkin_id": c.id,
            "patient_id": p.id,
            "patient_name": p.name,
            "patient_uid": p.patient_uid,
            "token_number": c.token_number,
            "doctor_id": d.id if d else None,
            "doctor_name": f"{d.title} {d.name}" if d else "—",
            "note": c.post_consult_note,
            "created_at": c.created_at.isoformat()
        })
    return result

@router.post("/post-consult/{checkin_id}")
def complete_post_consult(
    checkin_id: int,
    payload: NurseTaskComplete,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    _require_nurse(current_doctor)
    from app.routers.attendance import require_present
    require_present(db, current_doctor)

    checkin = db.query(Checkin).filter(
        Checkin.id == checkin_id,
        Checkin.hospital_id == current_doctor.hospital_id
    ).first()
    if not checkin:
        raise HTTPException(status_code=404, detail="Check-in not found")

    data = {k.strip(): v.strip() for k, v in payload.data.items() if k.strip() and v.strip()}
    if not data:
        raise HTTPException(status_code=400, detail="Notes are required to confirm this task was completed")

    checkin.post_consult_data = json.dumps(data)
    checkin.post_consult_status = "done"
    checkin.post_consult_recorded_by = current_doctor.id
    checkin.post_consult_recorded_at = now_ist_naive()
    db.commit()

    patient = db.query(Patient).filter(Patient.id == checkin.patient_id).first()
    log_action(
        db, current_doctor,
        action="post_consult_task_completed",
        target_type="patient",
        target_id=checkin.patient_id,
        target_label=f"{patient.name} ({patient.patient_uid})" if patient else str(checkin.patient_id),
        details=f"Token {checkin.token_number}"
    )
    return {"status": "done"}


@router.post("/opd-charge/{checkin_id}")
def add_opd_charge(
    checkin_id: int,
    payload: AddOpdChargeIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Ad-hoc OPD charge (dressing, injection, etc.) — goes straight to the
    bill, no approval gate, same principle as IPD's Other Charges."""
    _require_nurse(current_doctor)

    checkin = db.query(Checkin).filter(
        Checkin.id == checkin_id,
        Checkin.hospital_id == current_doctor.hospital_id
    ).first()
    if not checkin:
        raise HTTPException(status_code=404, detail="Check-in not found")
    if not payload.description.strip():
        raise HTTPException(status_code=400, detail="Description is required")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero")

    charge = OpdCharge(
        checkin_id=checkin.id, patient_id=checkin.patient_id, hospital_id=checkin.hospital_id,
        description=payload.description.strip(), amount=payload.amount, quantity=payload.quantity,
        added_by=current_doctor.id,
    )
    db.add(charge)
    db.commit()

    patient = db.query(Patient).filter(Patient.id == checkin.patient_id).first()
    log_action(
        db, current_doctor,
        action="opd_charge_added",
        target_type="patient",
        target_id=checkin.patient_id,
        target_label=f"{patient.name} ({patient.patient_uid})" if patient else str(checkin.patient_id),
        details=f"{payload.description} — Rs.{payload.amount * payload.quantity:.2f}"
    )
    return {"message": "Charge added"}