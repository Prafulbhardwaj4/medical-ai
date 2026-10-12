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
from app.models.master_test import MasterTest, MasterTestParameter  # noqa: E402
from app.models.master_medicine import MasterMedicine  # noqa: E402
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


# ---------------------------------------------------------------------------
# SAMPLE platform-wide master lists (LOCAL DEV ONLY - never auto-loaded in production).
# Master items have NO price. No HIV or radiology tests, ever.
# ---------------------------------------------------------------------------
# panel parameters: (name, unit, male range, female range, critical low, critical high)
MASTER_TESTS = [
    {"name": "Complete Blood Count (CBC)", "category": "Haematology", "tube": "EDTA (purple top)",
     "fasting": False, "tat": 4, "is_panel": True, "params": [
         ("Haemoglobin", "g/dL", "13.0-17.0", "12.0-15.0", 7.0, 20.0),
         ("Total Leucocyte Count", "/cumm", "4000-11000", "4000-11000", 2000.0, 30000.0),
         ("RBC Count", "million/cumm", "4.5-5.5", "3.8-4.8", None, None),
         ("Haematocrit (PCV)", "%", "40-50", "36-46", None, None),
         ("MCV", "fL", "83-101", "83-101", None, None),
         ("MCH", "pg", "27-32", "27-32", None, None),
         ("MCHC", "g/dL", "31.5-34.5", "31.5-34.5", None, None),
         ("Platelet Count", "lakh/cumm", "1.5-4.1", "1.5-4.1", 0.5, 10.0),
     ]},
    {"name": "Lipid Profile", "category": "Biochemistry", "tube": "Plain (red top)",
     "fasting": True, "tat": 6, "is_panel": True, "params": [
         ("Total Cholesterol", "mg/dL", "<200", "<200", None, None),
         ("Triglycerides", "mg/dL", "<150", "<150", None, None),
         ("HDL Cholesterol", "mg/dL", ">40", ">50", None, None),
         ("LDL Cholesterol", "mg/dL", "<100", "<100", None, None),
         ("VLDL Cholesterol", "mg/dL", "<30", "<30", None, None),
     ]},
    {"name": "Blood Sugar (Fasting)", "category": "Biochemistry", "tube": "Fluoride (grey top)",
     "fasting": True, "tat": 2, "unit": "mg/dL", "male": "70-100", "female": "70-100", "crit_low": 40.0, "crit_high": 500.0},
    {"name": "HbA1c", "category": "Biochemistry", "tube": "EDTA (purple top)",
     "fasting": False, "tat": 6, "unit": "%", "male": "4.0-5.6", "female": "4.0-5.6", "crit_low": None, "crit_high": None},
    {"name": "Serum Creatinine", "category": "Biochemistry", "tube": "Plain (red top)",
     "fasting": False, "tat": 4, "unit": "mg/dL", "male": "0.7-1.3", "female": "0.6-1.1", "crit_low": None, "crit_high": 10.0},
    {"name": "Blood Urea", "category": "Biochemistry", "tube": "Plain (red top)",
     "fasting": False, "tat": 4, "unit": "mg/dL", "male": "15-45", "female": "15-45", "crit_low": None, "crit_high": None},
    {"name": "Thyroid Stimulating Hormone (TSH)", "category": "Biochemistry", "tube": "Plain (red top)",
     "fasting": False, "tat": 8, "unit": "uIU/mL", "male": "0.4-4.2", "female": "0.4-4.2", "crit_low": None, "crit_high": None},
    {"name": "SGPT (ALT)", "category": "Biochemistry", "tube": "Plain (red top)",
     "fasting": False, "tat": 4, "unit": "U/L", "male": "7-56", "female": "7-45", "crit_low": None, "crit_high": None},
    {"name": "Serum Uric Acid", "category": "Biochemistry", "tube": "Plain (red top)",
     "fasting": False, "tat": 4, "unit": "mg/dL", "male": "3.5-7.2", "female": "2.6-6.0", "crit_low": None, "crit_high": None},
    {"name": "Urine Routine", "category": "Clinical Pathology", "tube": "Sterile urine container",
     "fasting": False, "tat": 2, "unit": "", "male": "", "female": "", "crit_low": None, "crit_high": None},
]

# generic, strength, form, schedule, default pack, billing mode, GST %
MASTER_MEDICINES = [
    ("Paracetamol", "500mg", "Tablet", "otc", 15, "per_pack", 12.0),
    ("Paracetamol", "125mg/5ml", "Syrup", "otc", 1, "per_unit", 12.0),
    ("Cetirizine", "10mg", "Tablet", "otc", 10, "per_pack", 12.0),
    ("Ibuprofen", "400mg", "Tablet", "otc", 10, "per_pack", 12.0),
    ("Amoxicillin", "500mg", "Capsule", "h", 10, "per_pack", 12.0),
    ("Azithromycin", "500mg", "Tablet", "h", 3, "per_pack", 12.0),
    ("Metformin", "500mg", "Tablet", "h", 10, "per_pack", 5.0),
    ("Amlodipine", "5mg", "Tablet", "h", 10, "per_pack", 12.0),
    ("Pantoprazole", "40mg", "Tablet", "h", 15, "per_pack", 12.0),
    ("Ceftriaxone", "1g", "Injection", "h", 1, "per_unit", 12.0),
    ("Salbutamol", "100mcg", "Inhaler", "h", 1, "per_unit", 12.0),
    ("Alprazolam", "0.25mg", "Tablet", "h1", 10, "per_pack", 12.0),
    ("Clonazepam", "0.5mg", "Tablet", "h1", 10, "per_pack", 12.0),
    ("Morphine", "10mg", "Injection", "x", 1, "per_unit", 12.0),
    ("Methylphenidate", "10mg", "Tablet", "x", 10, "per_pack", 12.0),
]


def seed_master_catalog(db):
    """Platform-wide (no hospital). Adds the sample lists only when the tables are empty."""
    if db.query(MasterTest).count() == 0:
        for t in MASTER_TESTS:
            is_panel = bool(t.get("is_panel"))
            mt = MasterTest(
                name=t["name"], category=t["category"], required_tube=t["tube"],
                fasting_required=t["fasting"], turnaround_hours=t["tat"], is_panel=is_panel,
                unit="" if is_panel else t.get("unit", ""),
                reference_range_male="" if is_panel else t.get("male", ""),
                reference_range_female="" if is_panel else t.get("female", ""),
                critical_low=None if is_panel else t.get("crit_low"),
                critical_high=None if is_panel else t.get("crit_high"),
                is_active=True,
            )
            db.add(mt)
            db.flush()
            for i, (pname, punit, pmale, pfemale, clow, chigh) in enumerate(t.get("params", [])):
                db.add(MasterTestParameter(
                    master_test_id=mt.id, name=pname, unit=punit,
                    reference_range_male=pmale, reference_range_female=pfemale,
                    critical_low=clow, critical_high=chigh, display_order=i, is_active=True,
                ))
        db.commit()
    if db.query(MasterMedicine).count() == 0:
        for generic, strength, form, sched, pack, mode, gst in MASTER_MEDICINES:
            db.add(MasterMedicine(
                generic_name=generic, strength=strength, dosage_form=form, schedule=sched,
                default_pack_size=pack, default_billing_mode=mode, gst_percent=gst,
                hsn_code="3004", is_active=True,
            ))
        db.commit()


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
        seed_master_catalog(db)
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