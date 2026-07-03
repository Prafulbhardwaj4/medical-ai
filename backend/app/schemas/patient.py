from pydantic import BaseModel, validator
from datetime import datetime, date
from typing import Optional

VALID_GENDERS = {"Male", "Female", "Other"}
VALID_BLOOD_GROUPS = {"A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"}

class PatientCreate(BaseModel):
    name: str
    phone: str
    age: int
    blood_group: Optional[str] = None
    gender: str

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

class PatientOut(BaseModel):
    id: int
    patient_uid: str
    name: str
    phone: str
    age: int
    blood_group: Optional[str] = None
    gender: str
    hospital_id: Optional[int] = None
    created_by: int
    created_at: datetime

    class Config:
        from_attributes = True

class PatientSummary(BaseModel):
    id: int
    patient_uid: str
    name: str
    phone: str
    age: int
    blood_group: Optional[str] = None
    gender: str
    last_visit: Optional[datetime] = None
    last_token: Optional[str] = None
    checked_in_today: bool = False

    class Config:
        from_attributes = True

class CheckinCreate(BaseModel):
    issue_category: str
    doctor_id: int

class CheckinOut(BaseModel):
    token_number: str
    patient_name: str
    doctor_name: str
    issue_category: str
    visit_date: date

    class Config:
        from_attributes = True

class DoctorLite(BaseModel):
    id: int
    title: str
    name: str
    specialization: str

    class Config:
        from_attributes = True