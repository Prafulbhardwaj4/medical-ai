from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import asyncio
import logging
import traceback
import re
import time
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
from app.routers import radiology_templates as radiology_templates_router
from app.routers import radiology as radiology_router
from app.routers import lab as lab_router
from app.routers import mlc_custody as mlc_custody_router
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
from app.routers import refunds as refunds_router
from app.routers import doctor_slots as doctor_slots_router
from app.routers import chat as chat_router
from app.routers import suggestions as suggestions_router
from app.routers import referrals as referrals_router
from app.routers import tutorials
from app.models.hospital import Hospital
from app.models.blacklisted_token import BlacklistedToken
from app.models.audit_log import AuditLog
from app.models.checkin import Checkin
from app.models.attendance import AttendanceRecord
from app.models.test_catalog import TestCatalogItem
from app.models.radiology_template import RadiologyTemplate
from app.models.radiology_template_section import RadiologyTemplateSection
from app.models.radiology_order import RadiologyOrder
from app.models.ai_scribe_topup import AiScribeTopup
from app.models.room import Room
from app.models.hospital_medicine import HospitalMedicine
from app.models.test_order import TestOrder
from app.models.medicine_batch import MedicineBatch
from app.models.medicine_order import MedicineOrder
from app.models.invoice import Invoice
from app.models.notification import Notification
from app.models.chat_message import ChatMessage
from app.models.opd_charge import OpdCharge
from app.models.admission_deposit import AdmissionDeposit, AdmissionDepositTopupRequest
from app.models.admission_tpa_case import AdmissionTpaCase
from app.models.refund import Refund
from app.models.day_end_close import DayEndClose
from app.config import settings
import warnings
import os
import logging
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

logging.basicConfig(level=logging.INFO, force=True)
logger = logging.getLogger("medscribe")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    force=True,
)
logger = logging.getLogger("medscribe")

if settings.SECRET_KEY == "changeme":
    warnings.warn("WARNING: SECRET_KEY is default. Set a strong key in .env before deploying.")

def _run_migrations():
    from alembic.config import Config as AlembicConfig
    from alembic import command as alembic_command

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    alembic_ini_path = os.path.join(backend_dir, "alembic.ini")

    db_url = settings.DATABASE_URL
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    alembic_cfg = AlembicConfig(alembic_ini_path)
    alembic_cfg.set_main_option("script_location", os.path.join(backend_dir, "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    try:
        alembic_command.upgrade(alembic_cfg, "heads")
    except Exception as e:
        logger.exception("Alembic migration failed; runtime schema sync will try to repair missing columns")
        warnings.warn(f"WARNING: alembic upgrade failed at startup: {e}")
        raise

_run_migrations()

# Import every model before create_all/schema sync.
import app.models  # noqa: F401

Base.metadata.create_all(bind=engine)


def _sql_literal(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _runtime_sync_schema():
    """
    Production rescue: Alembic in this repo has multiple heads and can leave
    Render's DB behind the SQLAlchemy models. create_all() will not add missing
    columns, so patch missing columns/tables at startup.
    """
    bind = engine
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    with bind.begin() as conn:
      for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            logger.warning("Creating missing table: %s", table.name)
            table.create(bind=conn, checkfirst=True)
            continue

        existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing_cols:
                continue
            if column.primary_key:
                continue

            col_type = column.type.compile(dialect=bind.dialect)
            default = None
            if column.default is not None and not callable(column.default.arg):
                default = _sql_literal(column.default.arg)
            if column.server_default is not None:
                default = str(column.server_default.arg).strip("'")

            sql = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'
            if default is not None:
                sql += f" DEFAULT {default}"

            logger.warning("Adding missing column: %s.%s", table.name, column.name)
            conn.execute(text(sql))


try:
    _runtime_sync_schema()
except SQLAlchemyError:
    logger.exception("Runtime schema sync failed")
    raise

security = HTTPBearer()
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="MedScribe API",
    version="0.1.0",
    swagger_ui_parameters={"persistAuthorization": True}
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.on_event("startup")
async def _start_midnight_scheduler():
    from app.scheduler import midnight_close_loop
    asyncio.create_task(midnight_close_loop())

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:5501",
        "http://127.0.0.1:5501",
        "https://medical-s-ai.vercel.app",
        "https://medical-ai-mvv1.onrender.com",
    ],
    allow_origin_regex=r"https://.*\.(vercel\.app|netlify\.app|onrender\.com)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    logger.info("REQ %s %s origin=%s", request.method, request.url.path, request.headers.get("origin"))
    try:
        response = await call_next(request)
    except Exception:
        logger.error("ERR %s %s\n%s", request.method, request.url.path, traceback.format_exc())
        raise
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    logger.info("RES %s %s status=%s duration_ms=%s", request.method, request.url.path, response.status_code, elapsed_ms)
    return response


_CORS_ALLOWED_ORIGINS = {
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:5501",
    "http://127.0.0.1:5501",
    "https://medical-s-ai.vercel.app",
    "https://medical-ai-mvv1.onrender.com",
}
_CORS_ORIGIN_REGEX = re.compile(r"https://.*\.(vercel\.app|netlify\.app|onrender\.com)$")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("UNHANDLED %s %s\n%s", request.method, request.url.path, traceback.format_exc())
    # TEMPORARY — surfaces the real exception in the response body itself,
    # since the Render log viewer isn't showing new entries right now.
    # REVERT this back to the generic message once the bug above is found;
    # exposing tracebacks to the client is not something to ship long-term.
    response = JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()},
    )
    # This handler is attached to Exception (not HTTPException), so Starlette
    # runs it from ServerErrorMiddleware, which wraps OUTSIDE CORSMiddleware.
    # That means CORSMiddleware never touches this response and the browser
    # reports it as a CORS failure ("No Access-Control-Allow-Origin header"),
    # masking the real 500 as what looks like a network/CORS error. Add the
    # header here by hand so real crashes surface as crashes, not phantom CORS.
    origin = request.headers.get("origin")
    if origin and (origin in _CORS_ALLOWED_ORIGINS or _CORS_ORIGIN_REGEX.match(origin)):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
    return response

app.include_router(auth_router.router)
app.include_router(patients_router.router)
app.include_router(consultations_router.router)
app.include_router(admin_router.router)
app.include_router(audit_router.router)
app.include_router(nurses_router.router)
app.include_router(attendance_router.router)
app.include_router(medicines_router.router)
app.include_router(tests_router.router)
app.include_router(radiology_templates_router.router)
app.include_router(radiology_router.router)
app.include_router(lab_router.router)
app.include_router(mlc_custody_router.router)
app.include_router(pharmacy_router.router)
app.include_router(billing_router.router)
app.include_router(notifications_router.router)
app.include_router(portal_auth_router.router)
app.include_router(portal_dashboard_router.router)
app.include_router(portal_hospitals_router.router)
app.include_router(portal_appointments_router.router)
app.include_router(portal_appointments_staff_router.router)
app.include_router(admissions_router.router)
app.include_router(refunds_router.router)
app.include_router(doctor_slots_router.router)
app.include_router(chat_router.router)
app.include_router(suggestions_router.router)
app.include_router(referrals_router.router)
app.include_router(tutorials.router)

os.makedirs("prescriptions", exist_ok=True)

@app.get("/")
def root():
    return {"status": "MedScribe API running"}

@app.get("/health")
def health():
    return {"status": "ok"}