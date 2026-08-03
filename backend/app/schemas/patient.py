from pydantic import BaseModel, validator
from datetime import datetime, date
from typing import Optional, Dict

VALID_GENDERS = {"Male", "Female", "Other"}
VALID_BLOOD_GROUPS = {"A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"}

class PatientMergeIn(BaseModel):
    primary_patient_id: int
    duplicate_patient_id: int
    phone_confirmed: bool  # reception ticks this only after confirming with the patient by phone — no ABHA yet to key off of


class PatientCreate(BaseModel):
    name: str
    phone: str
    age: int
    blood_group: Optional[str] = None
    gender: str
    abha_number: Optional[str] = None
    address: Optional[str] = None
    force: bool = False  # bypass the same-phone duplicate warning once reception has confirmed

    @validator("name")
    def validate_name(cls, v):
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Name must be at least 2 characters")
        if len(v) > 100:
            raise ValueError("Name is too long")
        return v

    @validator("phone")
    def validate_phone(cls, v):
        v = v.strip()
        import re
        if not re.match(r'^\+?[0-9]{10,13}$', v):
            raise ValueError("Invalid phone number")
        return v

    @validator("age")
    def validate_age(cls, v):
        if v < 0 or v > 120:
            raise ValueError("Age must be between 0 and 120")
        return v

    @validator("gender")
    def validate_gender(cls, v):
        v = v.strip().capitalize()
        if v not in VALID_GENDERS:
            raise ValueError(f"Gender must be one of {', '.join(VALID_GENDERS)}")
        return v

    @validator("blood_group")
    def validate_blood_group(cls, v):
        if v is None or v == "":
            return None
        v = v.strip().upper()
        if v not in VALID_BLOOD_GROUPS:
            raise ValueError(f"Blood group must be one of {', '.join(VALID_BLOOD_GROUPS)}")
        return v

    @validator("abha_number")
    def validate_abha(cls, v):
        if v is None or v.strip() == "":
            return None
        v = v.strip().replace("-", "").replace(" ", "")
        import re
        if not re.match(r'^[0-9]{14}$', v):
            raise ValueError("ABHA number must be 14 digits")
        return v


class EmergencyIntakeIn(BaseModel):
    name: Optional[str] = None
    approx_age: Optional[int] = None
    approx_gender: Optional[str] = None


class PatientOut(BaseModel):
    id: int
    patient_uid: str
    url_token: str
    name: str
    phone: str
    age: int
    blood_group: Optional[str] = None
    gender: str
    abha_number: Optional[str] = None
    address: Optional[str] = None
    hospital_id: Optional[int] = None
    created_by: int
    created_at: datetime

    class Config:
        from_attributes = True

class PatientSummary(BaseModel):
    id: int
    patient_uid: str
    url_token: str
    name: str
    phone: str
    age: int
    blood_group: Optional[str] = None
    gender: str
    last_visit: Optional[datetime] = None
    last_token: Optional[str] = None
    checked_in_today: bool = False
    currently_admitted: bool = False
    address: Optional[str] = None

    class Config:
        from_attributes = True

class CheckinCreate(BaseModel):
    issue_category: str
    doctor_id: int
    send_to_nurse: Optional[bool] = False
    consultation_fee: Optional[float] = None
    test_fee: Optional[float] = None

class CheckinOut(BaseModel):
    checkin_id: int
    token_number: str
    patient_name: str
    doctor_name: str
    issue_category: str
    visit_date: date
    nurse_name: Optional[str] = None
    consultation_fee: Optional[float] = None
    test_fee: Optional[float] = None
    total_fee: Optional[float] = None
    is_paid: bool = False

    class Config:
        from_attributes = True

class VitalsSubmit(BaseModel):
    data: Dict[str, str]

class NurseNoteCreate(BaseModel):
    note: str

class NurseTaskComplete(BaseModel):
    data: Dict[str, str] = {}

class AddOpdChargeIn(BaseModel):
    description: str
    amount: float
    quantity: int = 1

class PaymentMethodIn(BaseModel):
    payment_method: str  # "cash" | "card" | "upi"

    @validator("payment_method")
    def valid_method(cls, v):
        if v not in ("cash", "card", "upi"):
            raise ValueError("payment_method must be cash, card, or upi")
        return v


class DoctorLite(BaseModel):
    id: int
    doctor_uid: Optional[str] = None
    title: str
    name: str
    specialization: str
    on_duty_today: bool = False
    consultation_fee: Optional[float] = None
    room_number: Optional[str] = None
    attendance_status: Optional[str] = None  # present / on_break / off_duty / away_emergency / not_marked
    doctor_location: Optional[str] = None    # in_cabin / on_rounds — only set while attendance_status == "present"

    class Config:
        from_attributes = True


class MergeRequestIn(BaseModel):
    primary_patient_id: int   # the record that survives
    duplicate_patient_id: int  # the record that gets merged away
    reason: Optional[str] = None


class MergeConfirmIn(BaseModel):
    confirmation_note: str  # what was confirmed on the phone call with the patient — required, this is the human verification step