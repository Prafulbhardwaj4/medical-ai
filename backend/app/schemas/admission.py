from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class AdmitPatientIn(BaseModel):
    patient_id: int
    ward_type_id: Optional[int] = None  # preferred: pick from admin-configured ward types
    ward: Optional[str] = None          # fallback free-text, used only if ward_type_id is not given
    bed_number: str
    diagnosis: str
    daily_room_charge: float = 0        # fallback rate, used only if ward_type_id is not given
    admitting_doctor_id: Optional[int] = None  # defaults to the patient's last consulting doctor if not given


class UpdateDiagnosisIn(BaseModel):
    diagnosis: str


class WardTypeCreateIn(BaseModel):
    name: str
    total_beds: int
    daily_charge: float


class WardTypeOut(BaseModel):
    id: int
    name: str
    total_beds: int
    daily_charge: float
    occupied: int = 0
    vacant: int = 0

    class Config:
        from_attributes = True


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