from app.database import SessionLocal
from app.models.hospital import Hospital
from app.models.doctor import Doctor, UserRole
from app.utils.auth import hash_password

db = SessionLocal()
admin = Doctor(
    title="Dr.",
    name="Super Admin",
    email="admin@medscribe.in",
    phone="9999999999",
    specialization="Administration",
    clinic_name="MedScribe Admin",
    hashed_password=hash_password("YourStrongPassword123!"),
    role=UserRole.super_admin,
    hospital_id=None,
    is_active=True,
)
db.add(admin)
db.commit()
db.refresh(admin)
print(admin.id, admin.email, admin.role)