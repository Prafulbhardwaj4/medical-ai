from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import date, datetime
from pydantic import BaseModel

from app.database import get_db
from app.models.attendance import AttendanceRecord
from app.models.doctor import Doctor, UserRole
from app.utils.auth import get_current_doctor, ist_today
from app.utils.notify import sync_idle_staff_notification
from app.utils.timezone import now_ist_naive

router = APIRouter(prefix="/doctors", tags=["attendance"])

VALID_STATUSES = {"present", "on_break", "off_duty"}

class AttendanceMark(BaseModel):
    status: str
    room_id: Optional[int] = None

def get_today_attendance(db: Session, doctor_id: int):
    return db.query(AttendanceRecord).filter(
        AttendanceRecord.doctor_id == doctor_id,
        AttendanceRecord.date == ist_today()
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
            record.created_at = now_ist_naive()
            # shift_started_at deliberately NOT touched here — it stays pinned to
            # whenever they first arrived today, even if they toggle present/break/off_duty again
            if payload.room_id is not None:
                record.room_id = payload.room_id
        else:
            record = AttendanceRecord(
                doctor_id=current_doctor.id,
                hospital_id=current_doctor.hospital_id,
                date=ist_today(),
                status="present",
                room_id=payload.room_id,
                marked_by=current_doctor.id,
                shift_started_at=now_ist_naive()
            )
            db.add(record)
    else:
        if not record or record.status not in ("present", "on_break"):
            raise HTTPException(status_code=400, detail="Mark yourself present first.")
        record.status = status
        record.marked_by = current_doctor.id
        record.created_at = now_ist_naive()
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
            AttendanceRecord.date == ist_today()
        ).all()
    }

    from app.models.room import Room
    today_records = db.query(AttendanceRecord).filter(
        AttendanceRecord.hospital_id == current_doctor.hospital_id,
        AttendanceRecord.date == ist_today()
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

@router.get("/attendance/history")
def attendance_history(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    role: Optional[str] = None,
    doctor_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    try:
        start = datetime.strptime(from_date, "%Y-%m-%d").date() if from_date else (ist_today() - __import__("datetime").timedelta(days=30))
        end = datetime.strptime(to_date, "%Y-%m-%d").date() if to_date else ist_today()
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be in YYYY-MM-DD format")

    if start > end:
        raise HTTPException(status_code=400, detail="from_date must be before to_date")

    query = db.query(AttendanceRecord).filter(
        AttendanceRecord.hospital_id == current_doctor.hospital_id,
        AttendanceRecord.date >= start,
        AttendanceRecord.date <= end
    )
    if doctor_id:
        query = query.filter(AttendanceRecord.doctor_id == doctor_id)

    records = query.order_by(AttendanceRecord.date.desc()).all()

    staff_ids = {r.doctor_id for r in records}
    staff = {d.id: d for d in db.query(Doctor).filter(Doctor.id.in_(staff_ids)).all()} if staff_ids else {}

    if role and role != "all":
        records = [r for r in records if staff.get(r.doctor_id) and staff[r.doctor_id].role.value == role]

    return [
        {
            "doctor_id": r.doctor_id,
            "name": f"{staff[r.doctor_id].title} {staff[r.doctor_id].name}" if r.doctor_id in staff else "Unknown",
            "role": staff[r.doctor_id].role.value if r.doctor_id in staff else None,
            "date": r.date.isoformat(),
            "status": r.status,
            "shift_started_at": r.shift_started_at.isoformat() if r.shift_started_at else None,
            "last_updated_at": r.created_at.isoformat() if r.created_at else None
        }
        for r in records
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