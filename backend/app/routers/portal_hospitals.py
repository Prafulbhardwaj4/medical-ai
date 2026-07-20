from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.hospital import Hospital
from app.models.doctor import Doctor, UserRole
from app.schemas.portal import HospitalOut

router = APIRouter(prefix="/portal/hospitals", tags=["portal-hospitals"])


@router.get("/cities")
def list_cities(db: Session = Depends(get_db)):
    rows = db.query(Hospital.city).filter(Hospital.is_active == True, Hospital.city.isnot(None)).distinct().all()  # noqa: E712
    return sorted({r[0] for r in rows if r[0]})


@router.get("", response_model=list[HospitalOut])
def list_hospitals(city: Optional[str] = Query(None), db: Session = Depends(get_db)):
    q = db.query(Hospital).filter(Hospital.is_active == True)  # noqa: E712
    if city:
        q = q.filter(Hospital.city.ilike(f"%{city}%"))
    return q.order_by(Hospital.name).all()


@router.get("/{hospital_id}/doctors")
def list_hospital_doctors(hospital_id: int, db: Session = Depends(get_db)):
    doctors = db.query(Doctor).filter(
        Doctor.hospital_id == hospital_id,
        Doctor.role == UserRole.doctor,
        Doctor.is_active == True  # noqa: E712
    ).all()
    return [
        {
            "id": d.id, "name": f"{d.title} {d.name}", "specialization": d.specialization,
            "room_number": d.room_number, "consultation_fee": d.consultation_fee,
            "registration_number": d.registration_number,
        }
        for d in doctors
    ]


@router.get("/{hospital_id}/doctors/{doctor_id}/slots")
def list_doctor_slots(hospital_id: int, doctor_id: int, date: str, db: Session = Depends(get_db)):
    from datetime import datetime as dt
    from app.models.doctor_slot import DoctorSlot

    try:
        slot_date = dt.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

    slots = db.query(DoctorSlot).filter(
        DoctorSlot.hospital_id == hospital_id, DoctorSlot.doctor_id == doctor_id,
        DoctorSlot.slot_date == slot_date, DoctorSlot.is_booked == False  # noqa: E712
    ).order_by(DoctorSlot.slot_time).all()

    grouped = {"morning": [], "afternoon": [], "evening": []}
    for s in slots:
        grouped[s.period].append({"id": s.id, "time": s.slot_time})
    return grouped


@router.get("/{hospital_id}", response_model=HospitalOut)
def get_hospital(hospital_id: int, db: Session = Depends(get_db)):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id, Hospital.is_active == True).first()  # noqa: E712
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    return hospital