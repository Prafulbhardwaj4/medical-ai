from pydantic import BaseModel, Field, validator
from datetime import datetime, date
from typing import Optional, Dict, List

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
    date_of_birth: Optional[date] = None

    @validator("date_of_birth")
    def validate_dob(cls, v):
        if v is None:
            return v
        today = date.today()
        if v > today:
            raise ValueError("Date of birth can't be in the future")
        if (today - v).days > 365 * 120:
            raise ValueError("Date of birth looks wrong")
        return v
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


class PatientOut(BaseModel):
    id: int
    patient_uid: str
    url_token: str
    name: str
    phone: str
    age: int
    date_of_birth: Optional[date] = None
    blood_group: Optional[str] = None
    gender: str
    abha_number: Optional[str] = None
    address: Optional[str] = None
    hospital_id: Optional[int] = None
    created_by: int
    created_at: datetime
    auto_checked_in_token: Optional[str] = None  
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

class AdditionalDoctorIn(BaseModel):
    doctor_id: int
    consultation_fee: Optional[float] = Field(default=None, ge=0, le=100000)  # reception can override per doctor; falls back to that doctor's own default, same as the primary

class CheckinCreate(BaseModel):
    issue_category: str
    doctor_id: int
    send_to_nurse: Optional[bool] = True
    consultation_fee: Optional[float] = Field(default=None, ge=0, le=100000)
    test_fee: Optional[float] = Field(default=None, ge=0, le=1000000)
    force: Optional[bool] = False  # bypass the already-admitted warning once reception has confirmed
    duplicate_reason: Optional[str] = Field(default=None, max_length=200)  # required to issue a 2nd token to the same patient + doctor on the same day
    additional_doctors: Optional[List[AdditionalDoctorIn]] = None  # item 7 — one visit, multiple doctors, one Add Doctor step before Generate Token

class CheckinOut(BaseModel):
    checkin_id: int
    token_number: str
    visit_group_id: Optional[int] = None
    additional_tokens: Optional[List[dict]] = None
    patient_name: str
    patient_uid: Optional[str] = None
    doctor_name: str
    doctor_specialization: Optional[str] = None
    doctor_room_number: Optional[str] = None
    issue_category: str
    visit_date: date
    checked_in_at: Optional[datetime] = None
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
    description: str = Field(..., min_length=1, max_length=200)
    amount: float = Field(..., gt=0, le=1000000)
    quantity: int = Field(1, ge=1, le=1000)

class PaymentMethodIn(BaseModel):
    payment_method: str  # "cash" | "card" | "upi"

    @validator("payment_method")
    def valid_method(cls, v):
        if v not in ("cash", "card", "upi"):
            raise ValueError("payment_method must be cash, card, or upi")
        return v


class ReasonIn(BaseModel):
    reason: str

    @validator("reason")
    def valid_reason(cls, v):
        v = (v or "").strip()
        if len(v) < 5:
            raise ValueError("A reason of at least 5 characters is required")
        if len(v) > 300:
            raise ValueError("Reason is too long (300 characters max)")
        return v


class CollectAppointmentPaymentIn(PaymentMethodIn):
    fee_amount: Optional[float] = None
    late_choice: Optional[str] = None   # "next_slot" | "walk_in": required only when the payment is past the grace window
    slot_id: Optional[int] = None       # the new slot, when late_choice == "next_slot"


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


class PatientAllergyIn(BaseModel):
    allergen: str
    reaction: Optional[str] = None
    severity: str = "moderate"  # mild / moderate / severe