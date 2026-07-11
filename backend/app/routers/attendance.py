from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import date, datetime
from pydantic import BaseModel

from app.database import get_db
from app.models.attendance import AttendanceRecord
from app.models.doctor import Doctor, UserRole
from app.utils.auth import get_current_doctor
from app.utils.notify import sync_idle_staff_notification

router = APIRouter(prefix="/doctors", tags=["attendance"])

VALID_STATUSES = {"present", "on_break", "off_duty"}

class AttendanceMark(BaseModel):
    status: str
    room_id: Optional[int] = None

def get_today_attendance(db: Session, doctor_id: int):
    return db.query(AttendanceRecord).filter(
        AttendanceRecord.doctor_id == doctor_id,
        AttendanceRecord.date == date.today()
    ).first()

def require_present(db: Session, doctor: Doctor):
    record = get_today_attendance(db, doctor.id)
    if not record or record.status not in ("present", "on_break"):
        raise HTTPException(
            status_code=403,
            detail="Please mark your attendance as Present before starting work."
        )

@router.post("/attendance")
def mark_attendance(
    payload: AttendanceMark,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    status = payload.status.strip().lower()
    if status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {', '.join(VALID_STATUSES)}")

    if payload.room_id is not None:
        from app.models.room import Room
        room = db.query(Room).filter(
            Room.id == payload.room_id,
            Room.hospital_id == current_doctor.hospital_id,
            Room.is_active == True
        ).first()
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")

    record = get_today_attendance(db, current_doctor.id)

    if status == "present":
        if record:
            record.status = "present"
            record.marked_by = current_doctor.id
            record.created_at = datetime.utcnow()
            # shift_started_at deliberately NOT touched here — it stays pinned to
            # whenever they first arrived today, even if they toggle present/break/off_duty again
            if payload.room_id is not None:
                record.room_id = payload.room_id
        else:
            record = AttendanceRecord(
                doctor_id=current_doctor.id,
                hospital_id=current_doctor.hospital_id,
                date=date.today(),
                status="present",
                room_id=payload.room_id,
                marked_by=current_doctor.id,
                shift_started_at=datetime.utcnow()
            )
            db.add(record)
    else:
        if not record or record.status not in ("present", "on_break"):
            raise HTTPException(status_code=400, detail="Mark yourself present first.")
        record.status = status
        record.marked_by = current_doctor.id
        record.created_at = datetime.utcnow()
        if payload.room_id is not None:
            record.room_id = payload.room_id

    db.commit()

    if status == "off_duty":
        sync_idle_staff_notification(db, current_doctor)

    return {"status": record.status, "room_id": record.room_id}

@router.get("/attendance/today")
def attendance_today(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin", "super_admin", "doctor", "nurse", "receptionist", "lab", "pharmacy"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    staff = db.query(Doctor).filter(
        Doctor.hospital_id == current_doctor.hospital_id,
        Doctor.role.in_([UserRole.doctor, UserRole.sub_admin, UserRole.nurse, UserRole.receptionist, UserRole.lab, UserRole.pharmacy]),
        Doctor.is_active == True
    ).all()

    records = {
        r.doctor_id: r.status for r in db.query(AttendanceRecord).filter(
            AttendanceRecord.hospital_id == current_doctor.hospital_id,
            AttendanceRecord.date == date.today()
        ).all()
    }

    from app.models.room import Room
    today_records = db.query(AttendanceRecord).filter(
        AttendanceRecord.hospital_id == current_doctor.hospital_id,
        AttendanceRecord.date == date.today()
    ).all()
    room_ids_by_doctor = {r.doctor_id: r.room_id for r in today_records}
    room_names = {r.id: r.name for r in db.query(Room).filter(Room.hospital_id == current_doctor.hospital_id).all()}

    return [
        {
            "doctor_id": d.id,
            "name": f"{d.title} {d.name}",
            "specialization": d.specialization,
            "room_id": room_ids_by_doctor.get(d.id),
            "room_name": room_names.get(room_ids_by_doctor.get(d.id)) or "—",
            "role": d.role.value,
            "status": records.get(d.id, "not_marked")
        }
        for d in staff
    ]

@router.get("/attendance/my-status")
def my_attendance_status(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    record = get_today_attendance(db, current_doctor.id)
    if not record:
        return {"status": "not_marked", "room_id": None}
    return {"status": record.status, "room_id": record.room_id}