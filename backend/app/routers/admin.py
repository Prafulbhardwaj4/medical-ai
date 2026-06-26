from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.hospital import Hospital
from app.models.doctor import Doctor, UserRole
from app.utils.auth import hash_password
from app.config import settings
import secrets
from app.utils.auth import hash_password, get_current_doctor

router = APIRouter(prefix="/admin", tags=["admin"])

def verify_super_admin_key(x_super_admin_key: str = Header(...)):
    if x_super_admin_key != settings.SUPER_ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid super admin key")

@router.post("/hospitals", status_code=201)
def create_hospital(
    name: str,
    city: str,
    state: str,
    address: str = "",
    db: Session = Depends(get_db),
    _: None = Depends(verify_super_admin_key)
):
    # Auto-generate hospital code from name
    words = name.strip().upper().split()
    code_base = "".join([w[0] for w in words])[:4]
    hospital_code = f"{code_base}-{secrets.token_hex(3).upper()}"

    # Ensure unique
    while db.query(Hospital).filter(Hospital.hospital_code == hospital_code).first():
        hospital_code = f"{code_base}-{secrets.token_hex(3).upper()}"

    hospital = Hospital(
        name=name,
        address=address,
        city=city,
        state=state,
        hospital_code=hospital_code
    )
    db.add(hospital)
    db.commit()
    db.refresh(hospital)
    return {"id": hospital.id, "name": hospital.name, "hospital_code": hospital.hospital_code}

@router.post("/create-admin", status_code=201)
def create_admin(
    hospital_id: int,
    name: str,
    email: str,
    phone: str,
    password: str,
    title: str = "Dr.",
    specialization: str = "General",
    db: Session = Depends(get_db),
    _: None = Depends(verify_super_admin_key)
):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    email = email.lower().strip()
    existing = db.query(Doctor).filter(Doctor.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    admin = Doctor(
        title=title,
        name=name,
        email=email,
        phone=phone,
        specialization=specialization,
        clinic_name=hospital.name,
        hashed_password=hash_password(password),
        role=UserRole.admin,
        hospital_id=hospital_id,
        is_active=True
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return {
        "id": admin.id,
        "name": admin.name,
        "email": admin.email,
        "role": admin.role.value,
        "hospital": hospital.name,
        "hospital_code": hospital.hospital_code
    }

@router.get("/hospitals")
def list_hospitals(
    db: Session = Depends(get_db),
    _: None = Depends(verify_super_admin_key)
):
    hospitals = db.query(Hospital).all()
    return [{"id": h.id, "name": h.name, "hospital_code": h.hospital_code, "city": h.city, "is_active": h.is_active} for h in hospitals]

@router.post("/doctors", status_code=201)
def create_doctor(
    hospital_id: int,
    name: str,
    email: str,
    phone: str,
    password: str,
    specialization: str,
    title: str = "Dr.",
    registration_number: str = "",
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    # Only admin/sub_admin can create doctors
    if current_doctor.role.value not in ["admin", "sub_admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Admin can only create doctors for their own hospital
    if current_doctor.role.value != "super_admin" and current_doctor.hospital_id != hospital_id:
        raise HTTPException(status_code=403, detail="Cannot create doctor for another hospital")

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    email = email.lower().strip()
    existing = db.query(Doctor).filter(Doctor.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    doctor = Doctor(
        title=title,
        name=name,
        email=email,
        phone=phone,
        specialization=specialization,
        registration_number=registration_number,
        clinic_name=hospital.name,
        hashed_password=hash_password(password),
        role=UserRole.doctor,
        hospital_id=hospital_id,
        is_active=True,
        created_by=current_doctor.id
    )
    db.add(doctor)
    db.commit()
    db.refresh(doctor)
    return {
        "id": doctor.id,
        "name": doctor.name,
        "email": doctor.email,
        "role": doctor.role.value,
        "hospital": hospital.name
    }

@router.get("/doctors")
def list_doctors(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    doctors = db.query(Doctor).filter(
        Doctor.hospital_id == current_doctor.hospital_id,
        Doctor.role == UserRole.doctor
    ).all()

    return [
        {
            "id": d.id,
            "name": f"{d.title} {d.name}",
            "email": d.email,
            "phone": d.phone,
            "specialization": d.specialization,
            "is_active": d.is_active
        }
        for d in doctors
    ]

@router.patch("/doctors/{doctor_id}/toggle-active")
def toggle_doctor_active(
    doctor_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    doctor = db.query(Doctor).filter(
        Doctor.id == doctor_id,
        Doctor.hospital_id == current_doctor.hospital_id
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    doctor.is_active = not doctor.is_active
    db.commit()
    return {"id": doctor.id, "is_active": doctor.is_active}

@router.post("/create-superadmin", status_code=201)
def create_superadmin(
    name: str,
    email: str,
    phone: str,
    password: str,
    db: Session = Depends(get_db),
    _: None = Depends(verify_super_admin_key)
):
    email = email.lower().strip()
    existing = db.query(Doctor).filter(Doctor.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    superadmin = Doctor(
        title="",
        name=name,
        email=email,
        phone=phone,
        specialization="",
        clinic_name="",
        hashed_password=hash_password(password),
        role=UserRole.super_admin,
        hospital_id=None,
        is_active=True
    )
    db.add(superadmin)
    db.commit()
    db.refresh(superadmin)
    return {
        "id": superadmin.id,
        "name": superadmin.name,
        "email": superadmin.email,
        "role": superadmin.role.value
    }