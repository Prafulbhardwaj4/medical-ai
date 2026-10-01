"""
LOCAL DEV ONLY - fills your local SQLite database with demo hospitals.

Run from the backend folder (after copying .env.local.example to .env):

    python scripts/seed_local.py

Every demo hospital gets the SAME medicines, lab tests, patients and staff
roles. The only difference between them is the tier (see HOSPITALS below).
To add or change test data, edit the shared lists (STAFF, MEDICINES, TESTS,
PATIENTS) once and every hospital gets it.

Safe to run again: it only adds what is missing, and it re-marks all staff as
Present for today (attendance resets every day, and many actions are blocked
until staff are marked present).

For a completely clean start: stop the server, delete backend/medscribe.db,
then run this script again.

It refuses to run against anything except a local SQLite database.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402

if not settings.DATABASE_URL.startswith("sqlite"):
    sys.exit("REFUSING TO RUN: DATABASE_URL is not a local SQLite database. This script is for local dev only.")
if os.getenv("RENDER") or os.getenv("ENVIRONMENT", "").lower() == "production":
    sys.exit("REFUSING TO RUN: this looks like a production environment.")

import app.main  # noqa: E402,F401  (importing it creates the tables)
from app.database import SessionLocal  # noqa: E402
from app.models.doctor import Doctor, UserRole  # noqa: E402
from app.models.hospital import Hospital  # noqa: E402
from app.models.hospital_medicine import HospitalMedicine  # noqa: E402
from app.models.medicine_batch import MedicineBatch  # noqa: E402
from app.models.patient import Patient  # noqa: E402
from app.models.portal import PatientAccount, PatientProfileLink  # noqa: E402
from app.models.test_catalog import TestCatalogItem  # noqa: E402
from app.models.attendance import AttendanceRecord  # noqa: E402
from app.routers.admin import generate_doctor_uid  # noqa: E402
from app.routers.patients import generate_patient_uid, generate_url_token  # noqa: E402
from app.utils.auth import hash_password  # noqa: E402
from app.utils.portal_auth import hash_password as hash_portal_password  # noqa: E402
from app.utils.timezone import ist_today, now_ist_naive  # noqa: E402

PASSWORD = "Local@1234"
PORTAL_PHONE = "9811111111"  # patient portal login (same phone exists in every hospital)

# ---------------------------------------------------------------------------
# The ONLY thing that differs between demo hospitals is the tier.
# (code is used in the login email: doctor@<code>.example.com)
# ---------------------------------------------------------------------------
HOSPITALS = [
    ("DEMO", "Demo Foundation Hospital", "foundation"),
    ("GROW", "Demo Growth Hospital", "growth"),
]

# ---------------------------------------------------------------------------
# Shared test data - identical in every hospital.
# ---------------------------------------------------------------------------
# (email local-part, title, name, role, specialization)
STAFF = [
    ("admin", "Mr.", "Demo Admin", UserRole.admin, "Administration"),
    ("doctor", "Dr.", "Asha Verma", UserRole.doctor, "General Medicine"),
    ("doctor2", "Dr.", "Rohit Mehra", UserRole.doctor, "Paediatrics"),
    ("receptionist", "Ms.", "Neha Singh", UserRole.receptionist, "Front Desk"),
    ("nurse", "Ms.", "Pooja Kumari", UserRole.nurse, "Nursing"),
    ("pharmacy", "Mr.", "Amit Sharma", UserRole.pharmacy, "Pharmacy"),
    ("lab", "Mr.", "Vikas Yadav", UserRole.lab, "Pathology"),
]

# generic, strength, form, schedule, pack_size, price_per_pack, billing_mode, gst,
# batches = [(lot, quantity, days_until_expiry)]  (negative = already expired)
MEDICINES = [
    ("Paracetamol", "500mg", "Tablet", "otc", 15, 100.0, "per_pack", 12.0, [("PCM-A1", 60, 400)]),
    ("Amoxicillin", "500mg", "Capsule", "h", 10, 120.0, "per_pack", 12.0, [("AMX-B7", 40, 200)]),
    ("Cetirizine", "10mg", "Tablet", "otc", 10, 33.33, "per_pack", 12.0, [("CTZ-C2", 30, 25)]),   # near expiry
    ("Alprazolam", "0.25mg", "Tablet", "h1", 10, 45.0, "per_pack", 12.0, [("ALP-H1", 20, 300)]),  # Schedule H1
    ("Morphine", "10mg", "Injection", "x", 1, 60.0, "per_unit", 12.0, [("MOR-X1", 10, 300)]),     # Schedule X
    ("Ibuprofen", "400mg", "Tablet", "otc", 10, 40.0, "per_pack", 12.0,
     [("IBU-OLD", 50, -30), ("IBU-NEW", 20, 500)]),                                              # one EXPIRED lot
    ("Metformin", "500mg", "Tablet", "h", 10, 25.0, "per_pack", 5.0, [("MET-EXP", 40, -10)]),    # ONLY expired stock
]

# name, fee, category
TESTS = [
    ("Complete Blood Count (CBC)", 300.0, "Haematology"),
    ("Blood Sugar (Fasting)", 100.0, "Biochemistry"),
    ("Lipid Profile", 600.0, "Biochemistry"),
    ("Urine Routine", 150.0, "Clinical Pathology"),
]

# name, phone, age, gender  (the first patient is also the patient-portal login)
PATIENTS = [
    ("Ramesh Kumar", PORTAL_PHONE, 45, "Male"),
    ("Sunita Devi", "9822222222", 32, "Female"),
    ("Aarav Gupta", "9833333333", 7, "Male"),
]


def get_or_create_hospital(db, code, name, tier):
    h = db.query(Hospital).filter(Hospital.hospital_code == code).first()
    if h:
        return h
    h = Hospital(
        name=name, hospital_code=code, tier=tier, city="Panipat", state="Haryana",
        address="Local test address", hospital_type="private", billing_enabled=True,
        default_consultation_fee=300.0, is_active=True,
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    return h


def get_or_create_staff(db, hospital, key, title, name, role, spec):
    email = f"{key}@{hospital.hospital_code.lower()}.example.com"
    d = db.query(Doctor).filter(Doctor.email == email).first()
    if d:
        return d
    d = Doctor(
        doctor_uid=generate_doctor_uid(db, hospital.hospital_code),
        title=title, name=name, email=email, phone="9876543210",
        specialization=spec, registration_number="LOCAL-REG-001" if role == UserRole.doctor else None,
        clinic_name=hospital.name, hashed_password=hash_password(PASSWORD),
        role=role, hospital_id=hospital.id, is_active=True, must_change_password=False,
        consultation_fee=300.0 if role == UserRole.doctor else None,
        room_number="1" if role == UserRole.doctor else None,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def seed_superadmin(db):
    email = "superadmin@example.com"
    if db.query(Doctor).filter(Doctor.email == email).first():
        return
    db.add(Doctor(
        title="Mr.", name="Local Super Admin", email=email, phone="9000000000",
        specialization="Platform", clinic_name="MedScribe Platform",
        hashed_password=hash_password(PASSWORD),
        role=UserRole.super_admin, hospital_id=None, is_active=True, must_change_password=False,
    ))
    db.commit()


def seed_medicines(db, hospital):
    if db.query(HospitalMedicine).filter(HospitalMedicine.hospital_id == hospital.id).count():
        return
    today = date.today()
    for generic, strength, form, sched, pack, ppp, mode, gst, batches in MEDICINES:
        total = sum(q for _, q, _ in batches)
        m = HospitalMedicine(
            hospital_id=hospital.id, generic_name=generic, strength=strength,
            dosage_forms=form, schedule=sched, pack_size=pack, price_per_pack=ppp,
            price=round(ppp / pack, 2), billing_mode=mode, gst_percent=gst,
            stock_quantity=total, low_stock_threshold=10, is_active=True,
        )
        db.add(m)
        db.commit()
        db.refresh(m)
        for lot, qty, days in batches:
            db.add(MedicineBatch(
                medicine_id=m.id, hospital_id=hospital.id, batch_number=lot, quantity=qty,
                expiry_date=today + timedelta(days=days), received_date=today - timedelta(days=60),
            ))
        db.commit()


def seed_tests(db, hospital):
    if db.query(TestCatalogItem).filter(TestCatalogItem.hospital_id == hospital.id).count():
        return
    for name, fee, cat in TESTS:
        db.add(TestCatalogItem(hospital_id=hospital.id, name=name, fee=fee, category=cat, is_active=True))
    db.commit()


def seed_patients(db, hospital, doctor):
    if db.query(Patient).filter(Patient.hospital_id == hospital.id).count():
        return
    for name, phone, age, gender in PATIENTS:
        db.add(Patient(
            patient_uid=generate_patient_uid(db, hospital.id, hospital.hospital_code),
            url_token=generate_url_token(db), name=name, phone=phone, age=age,
            gender=gender, hospital_id=hospital.id, doctor_id=doctor.id, created_by=doctor.id,
        ))
        db.commit()


def seed_portal_account(db, hospitals):
    """One patient-portal login that sees the same phone's records in every hospital."""
    account = db.query(PatientAccount).filter(PatientAccount.phone == PORTAL_PHONE).first()
    if not account:
        account = PatientAccount(
            phone=PORTAL_PHONE, password_hash=hash_portal_password(PASSWORD),
            address="Local test address", is_active=True,
        )
        db.add(account)
        db.commit()
        db.refresh(account)
    for hospital in hospitals:
        patient = db.query(Patient).filter(
            Patient.hospital_id == hospital.id, Patient.phone == PORTAL_PHONE
        ).first()
        if not patient:
            continue
        if db.query(PatientProfileLink).filter(PatientProfileLink.patient_id == patient.id).first():
            continue
        db.add(PatientProfileLink(
            account_id=account.id, patient_id=patient.id, relation="self", linked_at=now_ist_naive()
        ))
    db.commit()


def mark_present_today(db, staff_list):
    today = ist_today()
    for d in staff_list:
        rec = db.query(AttendanceRecord).filter(
            AttendanceRecord.doctor_id == d.id, AttendanceRecord.date == today
        ).first()
        if rec:
            rec.status = "present"
            continue
        db.add(AttendanceRecord(
            doctor_id=d.id, hospital_id=d.hospital_id, date=today, status="present",
            doctor_location="in_cabin" if d.role == UserRole.doctor else None,
            marked_by=d.id, room_number=d.room_number, shift_started_at=now_ist_naive(),
        ))
    db.commit()


def main():
    db = SessionLocal()
    try:
        seed_superadmin(db)
        all_staff, hospitals = [], []
        for code, name, tier in HOSPITALS:
            hospital = get_or_create_hospital(db, code, name, tier)
            hospitals.append(hospital)
            staff = [get_or_create_staff(db, hospital, *s) for s in STAFF]
            all_staff += staff
            seed_medicines(db, hospital)
            seed_tests(db, hospital)
            seed_patients(db, hospital, next(s for s in staff if s.role == UserRole.doctor))
        seed_portal_account(db, hospitals)
        mark_present_today(db, all_staff)
    finally:
        db.close()

    print("\nLocal demo data is ready.\n")
    print(f"Password for every account: {PASSWORD}")
    print(f"Captcha answer on the login page: {settings.DEV_CAPTCHA_ANSWER or '(DEV_CAPTCHA_ANSWER is not set - solve the image)'}\n")
    print("Super admin:  superadmin@example.com")
    for code, name, tier in HOSPITALS:
        print(f"\n{name} ({tier} tier):")
        for key, *_rest in STAFF:
            print(f"   {key}@{code.lower()}.example.com")
    print(f"\nPatient portal login:  phone {PORTAL_PHONE}  (linked to Ramesh Kumar in every hospital)")
    print(f"\nEvery hospital has the same {len(MEDICINES)} medicines, {len(TESTS)} lab tests and {len(PATIENTS)} patients,")
    print("including an expired lot (Ibuprofen IBU-OLD), a medicine with ONLY expired stock (Metformin),")
    print("a near-expiry one (Cetirizine), a Schedule H1 (Alprazolam) and a Schedule X (Morphine) drug.\n")


if __name__ == "__main__":
    main()