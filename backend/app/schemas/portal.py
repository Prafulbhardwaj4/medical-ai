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
    slot_id: Optional[int] = None          # required for type="scheduled"
    requested_time: Optional[datetime] = None  # used only for type="queue_home"
    type: str = "scheduled"
    notes: Optional[str] = None


class AppointmentOut(BaseModel):
    id: int
    hospital_id: int
    hospital_name: Optional[str] = None
    doctor_id: Optional[int]
    doctor_name: Optional[str] = None
    type: str
    requested_time: datetime
    status: str
    payment_status: str = "unpaid"
    notes: Optional[str]

    class Config:
        from_attributes = True


class SaveTemplateIn(BaseModel):
    doctor_id: Optional[int] = None  # required if caller is admin/sub_admin/super_admin/receptionist
    weekdays: List[int]              # 0=Monday ... 6=Sunday
    morning_times: List[str] = []
    afternoon_times: List[str] = []
    evening_times: List[str] = []
    capacity_mode: str = "same"      # "same" | "per_period"
    capacity_same: int = 1
    capacity_morning: int = 1
    capacity_afternoon: int = 1
    capacity_evening: int = 1


class TemplateOut(BaseModel):
    exists: bool
    weekdays: List[int]
    morning_times: List[str]
    afternoon_times: List[str]
    evening_times: List[str]
    capacity_mode: str
    capacity_same: int
    capacity_morning: int
    capacity_afternoon: int
    capacity_evening: int


class MarkUnavailableIn(BaseModel):
    doctor_id: Optional[int] = None
    date: str
    reason: Optional[str] = None


class SlotOut(BaseModel):
    id: int
    slot_date: str
    slot_time: str
    period: str
    capacity: int
    booked_count: int

    class Config:
        from_attributes = True


class DoctorAppointmentCountOut(BaseModel):
    doctor_id: int
    doctor_name: str
    appointment_count: int


class DashboardStatsOut(BaseModel):
    profile_count: int
    consultation_count: int
    visit_count_total: int
    visit_count_last_30_days: int


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