from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional

class DoctorCreate(BaseModel):
    title: str = "Dr."
    name: str
    email: EmailStr
    phone: str
    specialization: str
    registration_number: str = ""
    clinic_name: str
    password: str

class DoctorLogin(BaseModel):
    email: EmailStr
    password: str

class DoctorOut(BaseModel):
    hospital_id: Optional[int] = None
    hospital_type: Optional[str] = None
    billing_enabled: bool = False
    default_consultation_fee: Optional[float] = None
    consultation_fee: Optional[float] = None
    id: int
    title: str
    name: str
    email: str
    phone: str
    specialization: str
    registration_number: Optional[str] = ""
    clinic_name: Optional[str] = ""
    role: str = "doctor"
    is_active: bool = True
    created_at: datetime

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    doctor: DoctorOut