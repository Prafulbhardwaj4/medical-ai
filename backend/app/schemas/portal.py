from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class InviteTokenInfo(BaseModel):
    masked_phone: str
    hospital_id: int


class RequestOTPIn(BaseModel):
    token: str


class VerifyOTPIn(BaseModel):
    token: str
    otp: str


class CompleteSignupIn(BaseModel):
    token: str
    otp: str
    password: str


class LoginIn(BaseModel):
    phone: str
    password: str


class PatientSessionOut(BaseModel):
    role: str
    name: str
    phone: str


class LoginResultOut(BaseModel):
    status: str
    access_token: Optional[str] = None
    doctor: Optional[PatientSessionOut] = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    doctor: Optional[PatientSessionOut] = None


class HospitalOut(BaseModel):
    id: int
    name: str
    city: Optional[str]
    address: Optional[str]

    class Config:
        from_attributes = True


class ProfileOut(BaseModel):
    id: int
    patient_id: int
    hospital_id: int
    hospital_name: str
    display_name: str
    relation: str
    linked_at: datetime


class DashboardOut(BaseModel):
    profiles: List[ProfileOut]
    records: dict  # {profile_link_id: {prescriptions, tests, invoices}}


class BookAppointmentIn(BaseModel):
    profile_link_id: Optional[int] = None
    hospital_id: int
    doctor_id: Optional[int] = None
    requested_time: datetime
    type: str = "scheduled"  # "scheduled" | "queue_home"
    notes: Optional[str] = None


class AppointmentOut(BaseModel):
    id: int
    hospital_id: int
    hospital_name: Optional[str] = None
    doctor_id: Optional[int]
    type: str
    requested_time: datetime
    status: str
    notes: Optional[str]

    class Config:
        from_attributes = True


class DashboardStatsOut(BaseModel):
    profile_count: int
    consultation_count: int
    visit_count: int


class ProfileSummaryOut(BaseModel):
    id: int  # profile_link_id
    patient_id: int
    hospital_id: int
    hospital_name: str
    display_name: str
    relation: str
    visit_count: int


class VisitOut(BaseModel):
    checkin_id: int
    token_number: str
    visit_date: str
    hospital_name: str
    doctor_name: Optional[str]
    patient_name: str
    has_prescription: bool
    has_invoice: bool
    test_count: int


class VisitTestOut(BaseModel):
    id: int
    test_name: str
    status: str


class VisitDetailOut(BaseModel):
    checkin_id: int
    token_number: str
    visit_date: str
    hospital_name: str
    doctor_name: Optional[str]
    patient_name: str
    consultation_id: Optional[int]
    diagnosis: Optional[str]
    invoice_id: Optional[int]
    invoice_total: Optional[float]
    tests: List[VisitTestOut]

class CompleteRegisterIn(BaseModel):
    phone: str
    new_password: str


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str