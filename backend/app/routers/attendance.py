from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import date, datetime
from pydantic import BaseModel

from app.database import get_db
from app.models.attendance import AttendanceRecord
from app.models.doctor import Doctor, UserRole
from app.utils.auth import get_current_doctor

router = APIRouter(prefix="/doctors", tags=["attendance"])

VALID_STATUSES = {"present", "on_break", "off_duty"}

class AttendanceMark(BaseModel):
    status: str

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

    record = get_today_attendance(db, current_doctor.id)

    if status == "present":
        if record and record.status == "present":
            raise HTTPException(status_code=400, detail="Already marked present for today.")
        if record:
            record.status = "present"
            record.marked_by = current_doctor.id
            record.created_at = datetime.utcnow()
        else:
            record = AttendanceRecord(
                doctor_id=current_doctor.id,
                hospital_id=current_doctor.hospital_id,
                date=date.today(),
                status="present",
                marked_by=current_doctor.id
            )
            db.add(record)
    else:
        if not record or record.status not in ("present", "on_break"):
            raise HTTPException(status_code=400, detail="Mark yourself present first.")
        record.status = status
        record.marked_by = current_doctor.id
        record.created_at = datetime.utcnow()

    db.commit()
    return {"status": record.status}

@router.get("/attendance/today")
def attendance_today(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin", "super_admin", "doctor", "nurse", "receptionist"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    staff = db.query(Doctor).filter(
        Doctor.hospital_id == current_doctor.hospital_id,
        Doctor.role.in_([UserRole.doctor, UserRole.sub_admin]),
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
            "room_number": d.room_number or "—",
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
    return {"status": record.status if record else "not_marked"}