from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class AdmitPatientIn(BaseModel):
    patient_id: int
    ward: str
    bed_number: str
    diagnosis: Optional[str] = None
    daily_room_charge: float = 0


class AdmissionSummaryOut(BaseModel):
    id: int
    patient_id: int
    patient_name: str
    patient_uid: Optional[str]
    ward: str
    bed_number: str
    status: str
    admission_date: datetime
    days_admitted: int


class AddMedicationOrderIn(BaseModel):
    medicine_id: Optional[int] = None
    medicine_name: str
    dosage: str
    route: str = "Oral"
    frequency_note: Optional[str] = None


class AdministerDoseIn(BaseModel):
    notes: Optional[str] = None


class AddChargeIn(BaseModel):
    charge_type: str  # "medicine" | "test" | "procedure" | "other"
    description: str
    amount: float
    quantity: int = 1


class AddAdmissionTestIn(BaseModel):
    test_id: Optional[int] = None
    test_name: str
    price: float = 0


class DischargeIn(BaseModel):
    discharge_summary: Optional[str] = None