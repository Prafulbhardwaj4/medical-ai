"""Which hospital does a master-list action work on?
A hospital user always works on their OWN hospital and may not pass a hospital id at all.
Only a super_admin (who has no hospital of their own) passes the hospital id, and must."""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.hospital import Hospital


def resolve_hospital(db: Session, doctor, hospital_id) -> Hospital:
    role = doctor.role.value
    if role == "super_admin":
        if not hospital_id:
            raise HTTPException(status_code=400, detail="Choose a hospital first (hospital_id is required).")
        hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
        if hospital is None:
            raise HTTPException(status_code=404, detail="Hospital not found.")
        return hospital
    if hospital_id is not None:
        raise HTTPException(status_code=403, detail="Only a super admin can act for another hospital.")
    if not doctor.hospital_id:
        raise HTTPException(status_code=400, detail="Your account is not linked to a hospital.")
    hospital = db.query(Hospital).filter(Hospital.id == doctor.hospital_id).first()
    if hospital is None:
        raise HTTPException(status_code=404, detail="Hospital not found.")
    return hospital