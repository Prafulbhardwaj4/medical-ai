from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.database import Base, engine
from app.routers import auth as auth_router
from app.routers import patients as patients_router
from app.routers import consultations as consultations_router
from app.routers import admin as admin_router
from app.routers import audit as audit_router
from app.routers import nurses as nurses_router
from app.routers import attendance as attendance_router
from app.routers import medicines as medicines_router
from app.routers import tests as tests_router
from app.routers import lab as lab_router
from app.routers import pharmacy as pharmacy_router
from app.routers import billing as billing_router
from app.routers import notifications as notifications_router
from app.routers import portal_auth as portal_auth_router
from app.routers import portal_dashboard as portal_dashboard_router
from app.routers import portal_hospitals as portal_hospitals_router
from app.routers import portal_appointments as portal_appointments_router
from app.models.portal import PatientAccount, PatientProfileLink, InviteStatus, OTPCode, Appointment
from app.routers import portal_appointments_staff as portal_appointments_staff_router
from app.routers import admissions as admissions_router
from app.routers import doctor_slots as doctor_slots_router
from app.routers import chat as chat_router
from app.models.hospital import Hospital
from app.models.blacklisted_token import BlacklistedToken
from app.models.audit_log import AuditLog
from app.models.checkin import Checkin
from app.models.attendance import AttendanceRecord
from app.models.test_catalog import TestCatalogItem
from app.models.room import Room
from app.models.hospital_medicine import HospitalMedicine
from app.models.test_order import TestOrder
from app.models.medicine_batch import MedicineBatch
from app.models.medicine_order import MedicineOrder
from app.models.invoice import Invoice
from app.models.notification import Notification
from app.models.chat_message import ChatMessage
from app.config import settings
import warnings
import os

if settings.SECRET_KEY == "changeme":
    warnings.warn("WARNING: SECRET_KEY is default. Set a strong key in .env before deploying.")

Base.metadata.create_all(bind=engine)

security = HTTPBearer()
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="MedScribe API",
    version="0.1.0",
    swagger_ui_parameters={"persistAuthorization": True}
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "https://medical-s-ai.vercel.app",
        "https://medical-ai-mvv1.onrender.com",
        ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(patients_router.router)
app.include_router(consultations_router.router)
app.include_router(admin_router.router)
app.include_router(audit_router.router)
app.include_router(nurses_router.router)
app.include_router(attendance_router.router)
app.include_router(medicines_router.router)
app.include_router(tests_router.router)
app.include_router(lab_router.router)
app.include_router(pharmacy_router.router)
app.include_router(billing_router.router)
app.include_router(notifications_router.router)
app.include_router(portal_auth_router.router)
app.include_router(portal_dashboard_router.router)
app.include_router(portal_hospitals_router.router)
app.include_router(portal_appointments_router.router)
app.include_router(portal_appointments_staff_router.router)
app.include_router(admissions_router.router)
app.include_router(doctor_slots_router.router)
app.include_router(chat_router.router)

os.makedirs("prescriptions", exist_ok=True)

@app.get("/")
def root():
    return {"status": "MedScribe API running"}

@app.get("/health")
def health():
    return {"status": "ok"}