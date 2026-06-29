from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class PatientCreate(BaseModel):
    name: str
    phone: str
    age: int
    blood_group: Optional[str] = None
    gender: str

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

    class Config:
        from_attributes = True