from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.hospital import Hospital
from app.models.doctor import Doctor, UserRole
from app.schemas.portal import HospitalOut

router = APIRouter(prefix="/portal/hospitals", tags=["portal-hospitals"])


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
        {"id": d.id, "name": f"{d.title} {d.name}", "specialization": d.specialization, "room_number": d.room_number}
        for d in doctors
    ]


@router.get("/{hospital_id}", response_model=HospitalOut)
def get_hospital(hospital_id: int, db: Session = Depends(get_db)):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id, Hospital.is_active == True).first()  # noqa: E712
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    return hospital