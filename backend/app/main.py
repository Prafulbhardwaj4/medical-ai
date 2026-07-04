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
from app.models.hospital import Hospital
from app.models.blacklisted_token import BlacklistedToken
from app.models.audit_log import AuditLog
from app.models.checkin import Checkin
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

os.makedirs("prescriptions", exist_ok=True)

@app.get("/")
def root():
    return {"status": "MedScribe API running"}

@app.get("/health")
def health():
    return {"status": "ok"}