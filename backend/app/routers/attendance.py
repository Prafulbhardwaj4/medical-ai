from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import date, datetime
from pydantic import BaseModel

from app.database import get_db
from app.models.attendance import AttendanceRecord
from app.models.doctor import Doctor, UserRole
from app.utils.auth import get_current_doctor, ist_today
from app.utils.notify import sync_idle_staff_notification, sync_idle_staff_notifications_for_hospital
from app.utils.timezone import now_ist_naive, IST

router = APIRouter(prefix="/doctors", tags=["attendance"])

VALID_STATUSES = {"present", "on_break", "off_duty"}
VALID_LOCATIONS = {"in_cabin", "on_rounds", "emergency"}
# "away_emergency" is deliberately NOT in VALID_STATUSES — it's system-set only,
# via set_away_for_emergency() below, never selectable through this endpoint.

class AttendanceMark(BaseModel):
    status: str
    room_id: Optional[int] = None
    expected_off_duty_at: Optional[str] = None  # ISO string from the browser, any timezone
    ward_ids: Optional[list[int]] = None    # nurse/assistant only — wards being covered
    doctor_ids: Optional[list[int]] = None  # nurse/assistant only — doctors/rooms being covered
    location: Optional[str] = None  # doctor only, status == "present" — "in_cabin" / "on_rounds"

def get_today_attendance(db: Session, doctor_id: int):
    return db.query(AttendanceRecord).filter(
        AttendanceRecord.doctor_id == doctor_id,
        AttendanceRecord.date == ist_today()
    ).first()

def parse_client_datetime(s: Optional[str]):
    """Parses a browser .toISOString() value into a naive IST datetime, this app's storage convention."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(IST).replace(tzinfo=None)
    except ValueError:
        return None

def auto_close_stale_shifts(db: Session, hospital_id: int):
    """Anyone still present/on_break past the off-duty time they gave us gets
    auto-marked off_duty. Runs lazily whenever attendance is read or written
    for the hospital, so it self-heals without needing a background job."""
    now = now_ist_naive()
    stale = db.query(AttendanceRecord).filter(
        AttendanceRecord.hospital_id == hospital_id,
        AttendanceRecord.status.in_(["present", "on_break"]),
        AttendanceRecord.expected_off_duty_at.isnot(None),
        AttendanceRecord.expected_off_duty_at < now,
    ).all()
    for rec in stale:
        rec.status = "off_duty"
        rec.auto_marked = 1
    if stale:
        db.commit()

    # Same lazy-on-read pattern as above: catch anyone idling mid-shift
    # (assigned work, done none of it, still clocked in) without a background job.
    sync_idle_staff_notifications_for_hospital(db, hospital_id)

def require_present(db: Session, doctor: Doctor):
    record = get_today_attendance(db, doctor.id)
    if not record or record.status not in ("present", "on_break"):
        raise HTTPException(
            status_code=403,
            detail="Please mark your attendance as Present before starting work."
        )

def set_away_for_emergency(db: Session, doctor_id: int, hospital_id: int):
    """System-only transition, called from admissions.py when an Emergency
    Alert interrupts a doctor mid-OPD-consultation. Never reachable through
    the normal /attendance toggle."""
    record = get_today_attendance(db, doctor_id)
    if not record or record.status not in ("present", "on_break"):
        return  # doctor isn't currently on an active shift — nothing to interrupt
    record.status = "away_emergency"
    record.doctor_location = None
    db.commit()

@router.post("/attendance")
def mark_attendance(
    payload: AttendanceMark,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    status = payload.status.strip().lower()
    if status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {', '.join(VALID_STATUSES)}")

    location = (payload.location or "").strip().lower() or None
    if location and location not in VALID_LOCATIONS:
        raise HTTPException(status_code=400, detail=f"location must be one of {', '.join(VALID_LOCATIONS)}")

    if payload.room_id is not None:
        from app.models.room import Room
        room = db.query(Room).filter(
            Room.id == payload.room_id,
            Room.hospital_id == current_doctor.hospital_id,
            Room.is_active == True
        ).first()
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")

    is_coverage_role = current_doctor.role.value in ("nurse", "assistant")
    ward_ids = list(dict.fromkeys(payload.ward_ids or []))
    doctor_ids = list(dict.fromkeys(payload.doctor_ids or []))
    if is_coverage_role and status == "present" and (ward_ids or doctor_ids):
        from app.models.admission_ward_type import AdmissionWardType
        if ward_ids:
            valid_wards = {w.id for w in db.query(AdmissionWardType.id).filter(
                AdmissionWardType.id.in_(ward_ids),
                AdmissionWardType.hospital_id == current_doctor.hospital_id
            ).all()}
            if len(valid_wards) != len(ward_ids):
                raise HTTPException(status_code=404, detail="One or more selected wards were not found")
        if doctor_ids:
            valid_doctors = {d.id for d in db.query(Doctor.id).filter(
                Doctor.id.in_(doctor_ids),
                Doctor.hospital_id == current_doctor.hospital_id,
                Doctor.role.in_([UserRole.doctor, UserRole.sub_admin])
            ).all()}
            if len(valid_doctors) != len(doctor_ids):
                raise HTTPException(status_code=404, detail="One or more selected doctors were not found")

    auto_close_stale_shifts(db, current_doctor.hospital_id)
    record = get_today_attendance(db, current_doctor.id)
    expected_off_duty_at = parse_client_datetime(payload.expected_off_duty_at)

    if status == "present":
        if record:
            starting_fresh_shift = record.status not in ("present", "on_break")
            record.status = "present"
            record.marked_by = current_doctor.id
            record.created_at = now_ist_naive()
            if starting_fresh_shift:
                record.expected_off_duty_at = expected_off_duty_at
            # else: preserve whatever off-duty time was set at shift start —
            # a room/location change or resuming from break isn't a new shift.
            record.auto_marked = 0
            record.doctor_location = location
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
                shift_started_at=now_ist_naive(),
                expected_off_duty_at=expected_off_duty_at,
                doctor_location=location
            )
            db.add(record)
    else:
        if not record or record.status not in ("present", "on_break"):
            raise HTTPException(status_code=400, detail="Mark yourself present first.")
        record.status = status
        record.marked_by = current_doctor.id
        record.created_at = now_ist_naive()
        record.doctor_location = None
        if status == "off_duty":
            record.expected_off_duty_at = None
            record.auto_marked = 0
        if payload.room_id is not None:
            record.room_id = payload.room_id

    db.commit()

    if is_coverage_role:
        from app.models.attendance_coverage import AttendanceCoverage
        if status == "present" and (ward_ids or doctor_ids):
            db.query(AttendanceCoverage).filter(AttendanceCoverage.attendance_record_id == record.id).delete()
            for wid in ward_ids:
                db.add(AttendanceCoverage(attendance_record_id=record.id, ward_type_id=wid))
            for did in doctor_ids:
                db.add(AttendanceCoverage(attendance_record_id=record.id, doctor_id=did))
            db.commit()
        elif status == "off_duty":
            db.query(AttendanceCoverage).filter(AttendanceCoverage.attendance_record_id == record.id).delete()
            db.commit()

    if status == "off_duty":
        sync_idle_staff_notification(db, current_doctor)

    coverage_out = {"ward_ids": ward_ids, "doctor_ids": doctor_ids} if is_coverage_role and status == "present" else None
    return {"status": record.status, "room_id": record.room_id, "location": record.doctor_location, "coverage": coverage_out}

@router.get("/attendance/today")
def attendance_today(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin", "super_admin", "doctor", "nurse", "assistant", "receptionist", "lab", "pharmacy"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    auto_close_stale_shifts(db, current_doctor.hospital_id)

    staff = db.query(Doctor).filter(
        Doctor.hospital_id == current_doctor.hospital_id,
        Doctor.role.in_([UserRole.doctor, UserRole.sub_admin, UserRole.nurse, UserRole.assistant, UserRole.receptionist, UserRole.lab, UserRole.pharmacy]),
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

    locations_by_doctor = {r.doctor_id: r.doctor_location for r in today_records}
    active_drafts = {
        d.id: d.active_consultation_id for d in staff if d.active_consultation_id
    }

    return [
        {
            "doctor_id": d.id,
            "name": f"{d.title} {d.name}",
            "specialization": d.specialization,
            "room_id": room_ids_by_doctor.get(d.id),
            "room_name": room_names.get(room_ids_by_doctor.get(d.id)) or "—",
            "role": d.role.value,
            "status": records.get(d.id, "not_marked"),
            "location": locations_by_doctor.get(d.id),
            "has_interrupted_draft": d.id in active_drafts
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

    auto_close_stale_shifts(db, current_doctor.hospital_id)

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

    records.sort(key=lambda r: (r.date, staff[r.doctor_id].name if r.doctor_id in staff else ""), reverse=False)
    records.sort(key=lambda r: r.date, reverse=True)  # date desc is primary; name asc (just set) is the stable secondary key

    return [
        {
            "doctor_id": r.doctor_id,
            "name": f"{staff[r.doctor_id].title} {staff[r.doctor_id].name}" if r.doctor_id in staff else "Unknown",
            "role": staff[r.doctor_id].role.value if r.doctor_id in staff else None,
            "date": r.date.isoformat(),
            "status": r.status,
            "shift_started_at": r.shift_started_at.isoformat() if r.shift_started_at else None,
            "last_updated_at": r.created_at.isoformat() if r.created_at else None,
            "auto_marked": bool(r.auto_marked)
        }
        for r in records
    ]

@router.get("/attendance/my-status")
def my_attendance_status(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    auto_close_stale_shifts(db, current_doctor.hospital_id)
    record = get_today_attendance(db, current_doctor.id)
    if not record:
        return {"status": "not_marked", "room_id": None, "location": None, "coverage": None, "active_consultation_id": current_doctor.active_consultation_id}
    coverage = None
    if current_doctor.role.value in ("nurse", "assistant") and record.status in ("present", "on_break"):
        from app.models.attendance_coverage import AttendanceCoverage
        rows = db.query(AttendanceCoverage).filter(AttendanceCoverage.attendance_record_id == record.id).all()
        coverage = {
            "ward_ids": [r.ward_type_id for r in rows if r.ward_type_id is not None],
            "doctor_ids": [r.doctor_id for r in rows if r.doctor_id is not None],
        }
    return {
        "status": record.status,
        "room_id": record.room_id,
        "location": record.doctor_location,
        "coverage": coverage,
        "active_consultation_id": current_doctor.active_consultation_id,
        "expected_off_duty_at": record.expected_off_duty_at.isoformat() if record.expected_off_duty_at else None,
    }


@router.patch("/attendance/off-duty-time")
def update_off_duty_time(
    body: dict,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Lets someone fix a wrong off-duty time without a full mark-off-duty
    then mark-present round trip — only makes sense while actually on an
    active shift."""
    record = get_today_attendance(db, current_doctor.id)
    if not record or record.status not in ("present", "on_break"):
        raise HTTPException(status_code=400, detail="You're not on an active shift right now")
    new_time = parse_client_datetime(body.get("expected_off_duty_at"))
    record.expected_off_duty_at = new_time
    db.commit()
    return {"expected_off_duty_at": record.expected_off_duty_at.isoformat() if record.expected_off_duty_at else None}