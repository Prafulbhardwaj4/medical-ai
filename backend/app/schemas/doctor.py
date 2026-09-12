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

class CaptchaOut(BaseModel):
    svg: str
    token: str

class DoctorLogin(BaseModel):
    email: EmailStr
    password: str
    captcha_token: str
    captcha_answer: str

class StaffLoginResultOut(BaseModel):
    status: str  # "success" | "needs_password_change"
    access_token: Optional[str] = None
    token_type: Optional[str] = "bearer"
    doctor: Optional["DoctorOut"] = None

class SetNewPasswordIn(BaseModel):
    email: EmailStr
    old_password: str
    new_password: str
    captcha_token: str
    captcha_answer: str

class ForgotPasswordRequestIn(BaseModel):
    email: EmailStr
    captcha_token: str
    captcha_answer: str

class ForgotPasswordVerifyIn(BaseModel):
    email: EmailStr
    otp: str

class ForgotPasswordVerifyOut(BaseModel):
    reset_token: str

class ResetPasswordIn(BaseModel):
    reset_token: str
    new_password: str

class EditMeIn(BaseModel):
    name: str
    phone: str
    registration_number: Optional[str] = ""
    title: Optional[str] = None

class DoctorOut(BaseModel):
    hospital_id: Optional[int] = None
    hospital_type: Optional[str] = None
    billing_enabled: bool = False
    hospital_tier: str = "growth"
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
    room_number: Optional[str] = None
    role: str = "doctor"
    is_active: bool = True
    is_hiv_authorized: bool = False
    created_at: datetime

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    doctor: DoctorOut