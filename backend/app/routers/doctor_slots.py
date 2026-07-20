from datetime import datetime as dt, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.doctor import Doctor, UserRole
from app.models.doctor_slot import DoctorSlot
from app.schemas.portal import GenerateSlotsIn, SlotOut
from app.utils.auth import get_current_doctor

router = APIRouter(prefix="/doctor-slots", tags=["doctor-slots"])

MANAGER_ROLES = {UserRole.admin, UserRole.sub_admin, UserRole.super_admin}


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


@router.post("/generate", response_model=list[SlotOut])
def generate_slots(
    body: GenerateSlotsIn,
    current_doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    target = _resolve_target_doctor(body.doctor_id, current_doctor, db)

    try:
        start = dt.strptime(body.start_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

    if not body.weekdays:
        raise HTTPException(status_code=400, detail="Select at least one day of the week")
    if body.days_count < 1 or body.days_count > 90:
        raise HTTPException(status_code=400, detail="days_count must be between 1 and 90")

    def capacity_for(period: str) -> int:
        if body.capacity_mode == "per_period":
            return {"morning": body.capacity_morning, "afternoon": body.capacity_afternoon, "evening": body.capacity_evening}[period]
        return body.capacity_same

    periods = {"morning": body.morning_times, "afternoon": body.afternoon_times, "evening": body.evening_times}
    created = []

    for offset in range(body.days_count):
        current_date = start + timedelta(days=offset)
        if current_date.weekday() not in body.weekdays:
            continue
        for period, times in periods.items():
            cap = capacity_for(period)
            for t in times:
                exists = db.query(DoctorSlot).filter(
                    DoctorSlot.doctor_id == target.id, DoctorSlot.slot_date == current_date, DoctorSlot.slot_time == t
                ).first()
                if exists:
                    continue
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
def my_slots(
    date: str,
    doctor_id: int = None,
    current_doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    target = _resolve_target_doctor(doctor_id, current_doctor, db) if current_doctor.role != UserRole.doctor else current_doctor
    try:
        slot_date = dt.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

    return db.query(DoctorSlot).filter(
        DoctorSlot.doctor_id == target.id, DoctorSlot.slot_date == slot_date
    ).order_by(DoctorSlot.slot_time).all()


@router.delete("/{slot_id}")
def delete_slot(
    slot_id: int,
    current_doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
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