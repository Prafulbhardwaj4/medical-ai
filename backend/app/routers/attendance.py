from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import date, datetime
from pydantic import BaseModel

from app.database import get_db
from app.models.attendance import AttendanceRecord
from app.models.doctor import Doctor
from app.utils.auth import get_current_doctor

router = APIRouter(prefix="/doctors", tags=["attendance"])

VALID_STATUSES = {"present", "on_break", "absent"}

class AttendanceMark(BaseModel):
    status: str

@router.post("/attendance")
def mark_attendance(
    payload: AttendanceMark,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    status = payload.status.strip().lower()
    if status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {', '.join(VALID_STATUSES)}")

    record = db.query(AttendanceRecord).filter(
        AttendanceRecord.doctor_id == current_doctor.id,
        AttendanceRecord.date == date.today()
    ).first()

    if record:
        record.status = status
        record.marked_by = current_doctor.id
        record.created_at = datetime.utcnow()
    else:
        record = AttendanceRecord(
            doctor_id=current_doctor.id,
            hospital_id=current_doctor.hospital_id,
            date=date.today(),
            status=status,
            marked_by=current_doctor.id
        )
        db.add(record)

    db.commit()
    return {"status": status}

@router.get("/attendance/today")
def attendance_today(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin", "doctor"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    staff = db.query(Doctor).filter(
        Doctor.hospital_id == current_doctor.hospital_id,
        Doctor.role.in_(["doctor", "sub_admin"]),
        Doctor.is_active == True
    ).all()

    records = {
        r.doctor_id: r.status for r in db.query(AttendanceRecord).filter(
            AttendanceRecord.hospital_id == current_doctor.hospital_id,
            AttendanceRecord.date == date.today()
        ).all()
    }

    return [
        {
            "doctor_id": d.id,
            "name": f"{d.title} {d.name}",
            "specialization": d.specialization,
            "status": records.get(d.id, "not_marked")
        }
        for d in staff
    ]