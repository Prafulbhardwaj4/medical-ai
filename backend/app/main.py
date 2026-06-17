from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from app.database import Base, engine
from app.routers import auth as auth_router
from app.routers import patients as patients_router
from app.routers import consultations as consultations_router
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.config import settings
import warnings
from fastapi.staticfiles import StaticFiles

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
    "http://localhost:8000",
    "http://127.0.0.1:8000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(patients_router.router)
app.include_router(consultations_router.router)

app.mount("/prescriptions", StaticFiles(directory="prescriptions"), name="prescriptions")

@app.get("/")
def root():
    return {"status": "MedScribe API running"}