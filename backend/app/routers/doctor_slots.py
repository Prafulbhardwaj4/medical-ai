import json
from datetime import datetime as dt, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.doctor import Doctor, UserRole
from app.models.doctor_slot import DoctorSlot
from app.models.doctor_availability import DoctorAvailabilityTemplate, DoctorUnavailability
from app.schemas.portal import SaveTemplateIn, TemplateOut, SlotOut, MarkUnavailableIn
from app.utils.auth import get_current_doctor
from app.utils.timezone import now_ist_naive

router = APIRouter(prefix="/doctor-slots", tags=["doctor-slots"])

MANAGER_ROLES = {UserRole.admin, UserRole.sub_admin, UserRole.super_admin, UserRole.receptionist}
REGEN_WINDOW_DAYS = 60


def _resolve_target_doctor(body_doctor_id, current_doctor, db: Session) -> Doctor:
    if current_doctor.role == UserRole.doctor:
        return current_doctor
    if current_doctor.role not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized to manage doctor availability")
    if not body_doctor_id:
        raise HTTPException(status_code=400, detail="doctor_id is required")
    doctor = db.query(Doctor).filter(Doctor.id == body_doctor_id, Doctor.hospital_id == current_doctor.hospital_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found in your hospital")
    return doctor


# ---------- Template (persistent weekly pattern) ----------

@router.get("/template", response_model=TemplateOut)
def get_template(doctor_id: int = None, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    target = _resolve_target_doctor(doctor_id, current_doctor, db)
    t = db.query(DoctorAvailabilityTemplate).filter(DoctorAvailabilityTemplate.doctor_id == target.id).first()
    if not t:
        return TemplateOut(
            exists=False, weekdays=[0, 1, 2, 3, 4, 5],
            morning_times=[], afternoon_times=[], evening_times=[],
            capacity_mode="same", capacity_same=1, capacity_morning=1, capacity_afternoon=1, capacity_evening=1,
        )
    return TemplateOut(
        exists=True, weekdays=json.loads(t.weekdays),
        morning_times=json.loads(t.morning_times), afternoon_times=json.loads(t.afternoon_times), evening_times=json.loads(t.evening_times),
        capacity_mode=t.capacity_mode, capacity_same=t.capacity_same,
        capacity_morning=t.capacity_morning, capacity_afternoon=t.capacity_afternoon, capacity_evening=t.capacity_evening,
    )


@router.post("/template", response_model=list[SlotOut])
def save_template(body: SaveTemplateIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    target = _resolve_target_doctor(body.doctor_id, current_doctor, db)

    if not body.weekdays:
        raise HTTPException(status_code=400, detail="Select at least one day of the week")
    if not body.morning_times and not body.afternoon_times and not body.evening_times:
        raise HTTPException(status_code=400, detail="Select at least one time slot")

    t = db.query(DoctorAvailabilityTemplate).filter(DoctorAvailabilityTemplate.doctor_id == target.id).first()
    if not t:
        t = DoctorAvailabilityTemplate(doctor_id=target.id, hospital_id=target.hospital_id)
        db.add(t)

    t.weekdays = json.dumps(body.weekdays)
    t.morning_times = json.dumps(body.morning_times)
    t.afternoon_times = json.dumps(body.afternoon_times)
    t.evening_times = json.dumps(body.evening_times)
    t.capacity_mode = body.capacity_mode
    t.capacity_same = body.capacity_same
    t.capacity_morning = body.capacity_morning
    t.capacity_afternoon = body.capacity_afternoon
    t.capacity_evening = body.capacity_evening
    t.updated_at = now_ist_naive()
    db.commit()

    return _regenerate_from_template(db, target, body)


def _regenerate_from_template(db: Session, target: Doctor, body: SaveTemplateIn) -> list[DoctorSlot]:
    """Wipes and rebuilds future UNBOOKED slots from the template. Booked
    slots (booked_count > 0) are never touched, so existing bookings stay
    valid even if the doctor changes their pattern afterward."""
    today = now_ist_naive().date()
    window_end = today + timedelta(days=REGEN_WINDOW_DAYS)

    db.query(DoctorSlot).filter(
        DoctorSlot.doctor_id == target.id,
        DoctorSlot.slot_date >= today, DoctorSlot.slot_date <= window_end,
        DoctorSlot.booked_count == 0,
    ).delete(synchronize_session=False)
    db.commit()

    unavailable_dates = {
        u.date for u in db.query(DoctorUnavailability).filter(
            DoctorUnavailability.doctor_id == target.id,
            DoctorUnavailability.date >= today, DoctorUnavailability.date <= window_end,
        ).all()
    }

    def capacity_for(period: str) -> int:
        if body.capacity_mode == "per_period":
            return {"morning": body.capacity_morning, "afternoon": body.capacity_afternoon, "evening": body.capacity_evening}[period]
        return body.capacity_same

    periods = {"morning": body.morning_times, "afternoon": body.afternoon_times, "evening": body.evening_times}
    created = []
    for offset in range(REGEN_WINDOW_DAYS + 1):
        current_date = today + timedelta(days=offset)
        if current_date.weekday() not in body.weekdays or current_date in unavailable_dates:
            continue
        for period, times in periods.items():
            cap = capacity_for(period)
            for t in times:
                slot = DoctorSlot(
                    doctor_id=target.id, hospital_id=target.hospital_id,
                    slot_date=current_date, slot_time=t, period=period, capacity=cap
                )
                db.add(slot)
                created.append(slot)
    db.commit()
    for s in created:
        db.refresh(s)
    return created


@router.get("/mine", response_model=list[SlotOut])
def my_slots(date: str, doctor_id: int = None, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    target = _resolve_target_doctor(doctor_id, current_doctor, db)
    try:
        slot_date = dt.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")
    return db.query(DoctorSlot).filter(
        DoctorSlot.doctor_id == target.id, DoctorSlot.slot_date == slot_date
    ).order_by(DoctorSlot.slot_time).all()


@router.delete("/{slot_id}")
def delete_slot(slot_id: int, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    slot = db.query(DoctorSlot).filter(DoctorSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")
    if current_doctor.role == UserRole.doctor and slot.doctor_id != current_doctor.id:
        raise HTTPException(status_code=403, detail="Not your slot")
    if current_doctor.role in MANAGER_ROLES and slot.hospital_id != current_doctor.hospital_id:
        raise HTTPException(status_code=403, detail="Not your hospital")
    if slot.booked_count > 0:
        raise HTTPException(status_code=400, detail="Cannot delete a slot that already has bookings")
    db.delete(slot)
    db.commit()
    return {"message": "Slot deleted"}


# ---------- Unavailability (doctor marked absent for a date) ----------

@router.post("/unavailable")
def mark_unavailable(body: MarkUnavailableIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    target = _resolve_target_doctor(body.doctor_id, current_doctor, db)
    try:
        the_date = dt.strptime(body.date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

    existing = db.query(DoctorUnavailability).filter(
        DoctorUnavailability.doctor_id == target.id, DoctorUnavailability.date == the_date
    ).first()
    if existing:
        return {"message": "Already marked unavailable for this date"}

    db.add(DoctorUnavailability(doctor_id=target.id, hospital_id=target.hospital_id, date=the_date, reason=body.reason))

    # Remove only unbooked future slots for that date — booked ones surface via /affected instead.
    db.query(DoctorSlot).filter(
        DoctorSlot.doctor_id == target.id, DoctorSlot.slot_date == the_date, DoctorSlot.booked_count == 0
    ).delete(synchronize_session=False)
    db.commit()
    return {"message": "Marked unavailable"}


@router.delete("/unavailable/{unavailability_id}")
def unmark_unavailable(unavailability_id: int, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    row = db.query(DoctorUnavailability).filter(DoctorUnavailability.id == unavailability_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    if current_doctor.role == UserRole.doctor and row.doctor_id != current_doctor.id:
        raise HTTPException(status_code=403, detail="Not your record")
    db.delete(row)
    db.commit()
    return {"message": "Unavailability removed"}


@router.get("/unavailable")
def list_unavailable(doctor_id: int = None, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    target = _resolve_target_doctor(doctor_id, current_doctor, db)
    today = now_ist_naive().date()
    rows = db.query(DoctorUnavailability).filter(
        DoctorUnavailability.doctor_id == target.id, DoctorUnavailability.date >= today
    ).order_by(DoctorUnavailability.date).all()
    return [{"id": r.id, "date": r.date.isoformat(), "reason": r.reason} for r in rows]


@router.get("/unavailable/{date}/affected-appointments")
def affected_appointments(date: str, doctor_id: int = None, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    """Paid appointments that were already booked before the doctor was
    marked unavailable — these need manual staff handling (reschedule,
    reassign, or refund), since we don't auto-cancel a paid booking."""
    from app.models.portal import Appointment, AppointmentStatus

    target = _resolve_target_doctor(doctor_id, current_doctor, db)
    try:
        the_date = dt.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

    start = dt.combine(the_date, dt.min.time())
    end = start + timedelta(days=1)

    appts = db.query(Appointment).filter(
        Appointment.doctor_id == target.id,
        Appointment.payment_status == "paid",
        Appointment.status.in_([AppointmentStatus.booked, AppointmentStatus.confirmed]),
        Appointment.requested_time >= start, Appointment.requested_time < end,
    ).all()

    result = []
    for a in appts:
        name = a.profile_link.patient.name if a.profile_link and a.profile_link.patient else "Unknown patient"
        result.append({"appointment_id": a.id, "patient_name": name, "requested_time": a.requested_time.isoformat()})
    return result