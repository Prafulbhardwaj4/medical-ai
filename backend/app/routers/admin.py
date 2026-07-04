from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.hospital import Hospital
from app.models.doctor import Doctor, UserRole
from app.utils.auth import hash_password
from app.config import settings
import secrets
from app.utils.auth import hash_password, get_current_doctor
from app.utils.audit import log_action
import re
from app.models.consultation import Consultation
from sqlalchemy import func
from datetime import datetime, timedelta

router = APIRouter(prefix="/admin", tags=["admin"])

def verify_super_admin_key(x_super_admin_key: str = Header(...)):
    if x_super_admin_key != settings.SUPER_ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid super admin key")

import re

def validate_fields(name, email, phone, password):
    if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
        raise HTTPException(status_code=400, detail="Invalid email format")
    if not re.match(r'^\+?[0-9]{10,13}$', phone):
        raise HTTPException(status_code=400, detail="Invalid phone number")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if not re.search(r'[0-9]', password):
        raise HTTPException(status_code=400, detail="Password must contain at least one number")
    if not re.search(r'[A-Z]', password):
        raise HTTPException(status_code=400, detail="Password must contain at least one uppercase letter")
    if len(name.strip()) < 2:
        raise HTTPException(status_code=400, detail="Name too short")

VALID_HOSPITAL_TYPES = {"government", "private"}

@router.post("/hospitals", status_code=201)
def create_hospital(
    name: str,
    city: str,
    state: str,
    address: str = "",
    hospital_type: str = "private",
    db: Session = Depends(get_db),
    _: None = Depends(verify_super_admin_key)
):
    hospital_type = hospital_type.strip().lower()
    if hospital_type not in VALID_HOSPITAL_TYPES:
        raise HTTPException(status_code=400, detail="hospital_type must be 'government' or 'private'")

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
        hospital_code=hospital_code,
        hospital_type=hospital_type
    )
    db.add(hospital)
    db.commit()
    db.refresh(hospital)
    return {"id": hospital.id, "name": hospital.name, "hospital_code": hospital.hospital_code, "hospital_type": hospital.hospital_type}

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
    
    validate_fields(name, email, phone, password)

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
    return [{"id": h.id, "name": h.name, "hospital_code": h.hospital_code, "hospital_type": h.hospital_type, "city": h.city, "is_active": h.is_active} for h in hospitals]

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
    role: str = "doctor",
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    # Only admin/sub_admin can create doctors
    if current_doctor.role.value not in ["admin", "sub_admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    if role not in ["doctor", "sub_admin", "receptionist", "nurse"]:
        raise HTTPException(status_code=400, detail="Invalid role")

    if current_doctor.role.value == "sub_admin" and role != "doctor":
        raise HTTPException(status_code=403, detail="Sub admin can only create doctor accounts")

    # Admin can only create doctors for their own hospital
    if current_doctor.role.value != "super_admin" and current_doctor.hospital_id != hospital_id:
        raise HTTPException(status_code=403, detail="Cannot create doctor for another hospital")

    validate_fields(name, email, phone, password)

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
        role=UserRole(role),
        hospital_id=hospital_id,
        is_active=True,
        created_by=current_doctor.id
    )
    db.add(doctor)
    db.commit()
    db.refresh(doctor)

    log_action(
        db, current_doctor,
        action="account_created",
        target_type="doctor",
        target_id=doctor.id,
        target_label=f"{doctor.title} {doctor.name}",
        details=f"Created as {doctor.role.value} in {hospital.name}"
    )

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
        Doctor.role.in_([UserRole.doctor, UserRole.sub_admin, UserRole.receptionist, UserRole.nurse])
    ).all()

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)

    result = []
    for d in doctors:
        total = db.query(Consultation).filter(
            Consultation.doctor_id == d.id,
            Consultation.token_number != None,
            Consultation.is_voided == False
        ).count()
        today = db.query(Consultation).filter(
            Consultation.doctor_id == d.id,
            Consultation.token_number != None,
            Consultation.is_voided == False,
            Consultation.created_at >= today_start
        ).count()
        week = db.query(Consultation).filter(
            Consultation.doctor_id == d.id,
            Consultation.token_number != None,
            Consultation.is_voided == False,
            Consultation.created_at >= week_start
        ).count()
        result.append({
            "id": d.id,
            "name": f"{d.title} {d.name}",
            "email": d.email,
            "phone": d.phone,
            "specialization": d.specialization,
            "registration_number": d.registration_number or "",
            "is_active": d.is_active,
            "role": d.role.value,
            "consultations_today": today,
            "consultations_week": week,
            "consultations_total": total
        })
    return result

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

    # Prevent deactivating yourself
    if doctor.id == current_doctor.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")

    # sub_admin cannot deactivate admin or other sub_admins
    if current_doctor.role.value == "sub_admin" and doctor.role.value in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Sub admin cannot deactivate admin accounts")

    # admin cannot deactivate other admins or sub_admins
    if current_doctor.role.value == "admin" and doctor.role.value in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Cannot deactivate admin or sub admin accounts")

    doctor.is_active = not doctor.is_active
    db.commit()

    log_action(
        db, current_doctor,
        action="account_activated" if doctor.is_active else "account_deactivated",
        target_type="doctor",
        target_id=doctor.id,
        target_label=f"{doctor.title} {doctor.name}"
    )

    return {"id": doctor.id, "is_active": doctor.is_active}


@router.patch("/doctors/{doctor_id}/toggle-role")
def toggle_doctor_role(
    doctor_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Only admin or super admin can change roles")

    doctor = db.query(Doctor).filter(
        Doctor.id == doctor_id,
        Doctor.hospital_id == current_doctor.hospital_id
    ).first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    if doctor.id == current_doctor.id:
        raise HTTPException(status_code=400, detail="You cannot change your own role")

    if doctor.role.value not in ["doctor", "sub_admin"]:
        raise HTTPException(status_code=400, detail="Can only toggle role between doctor and sub admin")

    old_role = doctor.role.value
    doctor.role = UserRole.doctor if doctor.role.value == "sub_admin" else UserRole.sub_admin
    db.commit()

    log_action(
        db, current_doctor,
        action="role_changed",
        target_type="doctor",
        target_id=doctor.id,
        target_label=f"{doctor.title} {doctor.name}",
        details=f"{old_role} → {doctor.role.value}"
    )

    return {"id": doctor.id, "role": doctor.role.value}

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

@router.post("/create-subadmin", status_code=201)
def create_subadmin(
    hospital_id: int,
    name: str,
    email: str,
    phone: str,
    password: str,
    specialization: str,
    title: str = "Dr.",
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    if current_doctor.role.value != "super_admin" and current_doctor.hospital_id != hospital_id:
        raise HTTPException(status_code=403, detail="Cannot create sub admin for another hospital")

    validate_fields(name, email, phone, password)

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    email = email.lower().strip()
    existing = db.query(Doctor).filter(Doctor.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    subadmin = Doctor(
        title=title,
        name=name,
        email=email,
        phone=phone,
        specialization=specialization,
        clinic_name=hospital.name,
        hashed_password=hash_password(password),
        role=UserRole.sub_admin,
        hospital_id=hospital_id,
        is_active=True,
        created_by=current_doctor.id
    )
    db.add(subadmin)
    db.commit()
    db.refresh(subadmin)
    return {
        "id": subadmin.id,
        "name": subadmin.name,
        "email": subadmin.email,
        "role": subadmin.role.value,
        "hospital": hospital.name
    }

@router.get("/hospitals-list")
def list_hospitals_jwt(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    
    hospitals = db.query(Hospital).all()
    return [
        {
            "id": h.id,
            "name": h.name,
            "hospital_code": h.hospital_code,
            "hospital_type": h.hospital_type,
            "city": h.city,
            "is_active": h.is_active
        }
        for h in hospitals
    ]

@router.patch("/hospitals/{hospital_id}/toggle-active")
def toggle_hospital_active(
    hospital_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    hospital.is_active = not hospital.is_active
    db.commit()

    log_action(
        db, current_doctor,
        action="hospital_activated" if hospital.is_active else "hospital_deactivated",
        target_type="hospital",
        target_id=hospital.id,
        target_label=hospital.name,
        hospital_id=hospital.id
    )

    return {"id": hospital.id, "is_active": hospital.is_active}


@router.post("/hospitals-jwt", status_code=201)
def create_hospital_jwt(
    name: str,
    city: str,
    state: str,
    address: str = "",
    hospital_type: str = "private",
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    hospital_type = hospital_type.strip().lower()
    if hospital_type not in VALID_HOSPITAL_TYPES:
        raise HTTPException(status_code=400, detail="hospital_type must be 'government' or 'private'")

    words = name.strip().upper().split()
    code_base = "".join([w[0] for w in words])[:4]
    hospital_code = f"{code_base}-{secrets.token_hex(3).upper()}"
    while db.query(Hospital).filter(Hospital.hospital_code == hospital_code).first():
        hospital_code = f"{code_base}-{secrets.token_hex(3).upper()}"

    hospital = Hospital(name=name, address=address, city=city, state=state, hospital_code=hospital_code, hospital_type=hospital_type)
    db.add(hospital)
    db.commit()
    db.refresh(hospital)

    log_action(
        db, current_doctor,
        action="hospital_created",
        target_type="hospital",
        target_id=hospital.id,
        target_label=hospital.name,
        hospital_id=hospital.id
    )
    return {"id": hospital.id, "name": hospital.name, "hospital_code": hospital.hospital_code, "hospital_type": hospital.hospital_type}

@router.post("/create-admin-jwt", status_code=201)
def create_admin_jwt(
    hospital_id: int,
    name: str,
    email: str,
    phone: str,
    specialization: str,
    password: str,
    title: str = "Dr.",
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    validate_fields(name, email, phone, password)

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    email = email.lower().strip()
    existing = db.query(Doctor).filter(Doctor.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    admin = Doctor(
        title=title, name=name, email=email, phone=phone,
        specialization=specialization, clinic_name=hospital.name,
        hashed_password=hash_password(password),
        role=UserRole.admin, hospital_id=hospital_id, is_active=True
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)

    log_action(
        db, current_doctor,
        action="account_created",
        target_type="doctor",
        target_id=admin.id,
        target_label=f"{admin.title} {admin.name}",
        details=f"Created as admin in {hospital.name}",
        hospital_id=hospital_id
    )

    return {"id": admin.id, "name": admin.name, "email": admin.email, "role": admin.role.value}

@router.get("/stats")
def superadmin_stats(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    from datetime import datetime
    import pytz
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    total_hospitals = db.query(Hospital).filter(Hospital.is_active == True).count()
    total_doctors = db.query(Doctor).filter(
        Doctor.role == UserRole.doctor,
        Doctor.is_active == True
    ).count()
    new_hospitals_this_month = db.query(Hospital).filter(
        Hospital.created_at >= month_start
    ).count()
    new_doctors_this_month = db.query(Doctor).filter(
        Doctor.role == UserRole.doctor,
        Doctor.created_at >= month_start
    ).count()

    monthly_revenue = total_doctors * 499

    return {
        "total_hospitals": total_hospitals,
        "total_doctors": total_doctors,
        "new_hospitals_this_month": new_hospitals_this_month,
        "new_doctors_this_month": new_doctors_this_month,
        "monthly_revenue": monthly_revenue
    }

@router.get("/hospital/{hospital_id}")
def hospital_detail(
    hospital_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    admins = db.query(Doctor).filter(
        Doctor.hospital_id == hospital_id,
        Doctor.role.in_([UserRole.admin, UserRole.sub_admin])
    ).all()

    doctors = db.query(Doctor).filter(
        Doctor.hospital_id == hospital_id,
        Doctor.role == UserRole.doctor
    ).all()

    return {
        "id": hospital.id,
        "name": hospital.name,
        "city": hospital.city,
        "state": hospital.state,
        "address": hospital.address,
        "hospital_code": hospital.hospital_code,
        "hospital_type": hospital.hospital_type,
        "is_active": hospital.is_active,
        "created_at": hospital.created_at.isoformat(),
        "admins": [
            {
                "id": a.id,
                "name": f"{a.title} {a.name}",
                "email": a.email,
                "phone": a.phone,
                "role": a.role.value,
                "is_active": a.is_active
            }
            for a in admins
        ],
        "doctors": [
            {
                "id": d.id,
                "name": f"{d.title} {d.name}",
                "specialization": d.specialization,
                "is_active": d.is_active
            }
            for d in doctors
        ],
        "doctor_count": len(doctors),
        "monthly_revenue": len(doctors) * 499
    }