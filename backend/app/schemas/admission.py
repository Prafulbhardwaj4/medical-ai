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
    deposit_amount: float = 0           # pre-filled from ward type's default, reception can override
    deposit_payment_method: Optional[str] = None  # required if deposit_amount > 0


class UpdateDiagnosisIn(BaseModel):
    diagnosis: str


class SendToAdmissionIn(BaseModel):
    patient_id: int
    reason: Optional[str] = None


class WardTypeCreateIn(BaseModel):
    name: str
    total_beds: int
    daily_charge: float
    default_deposit: float = 0
    is_icu: bool = False


class WardTypeOut(BaseModel):
    id: int
    name: str
    total_beds: int
    daily_charge: float
    default_deposit: float = 0
    is_icu: bool = False
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


class ReturnMedicationIn(BaseModel):
    quantity: int
    restock: bool = False
    note: Optional[str] = None


class EmergencyAlertIn(BaseModel):
    message: Optional[str] = None


class AddAdmissionTestIn(BaseModel):
    test_id: Optional[int] = None
    test_name: str
    price: float = 0


class RequestWardChangeIn(BaseModel):
    requested_ward_type_id: int
    note: Optional[str] = None


class ChangeWardIn(BaseModel):
    ward_type_id: int
    bed_number: str


class DischargeIn(BaseModel):
    discharge_summary: Optional[str] = None
    payment_collected: bool = False
    payment_method: Optional[str] = None  # "cash" | "card" | "upi", required when payment_collected is True
    refund_channel: Optional[str] = None  # "cash" | "card" | "upi" | "online", required when the deposit exceeds charges


class TopupRequestIn(BaseModel):
    requested_amount: float
    reason: Optional[str] = None


class CollectTopupIn(BaseModel):
    payment_method: str  # "cash" | "card" | "upi"


class TpaCaseIn(BaseModel):
    insurer_name: str
    policy_number: Optional[str] = None
    room_category_eligibility: Optional[str] = None
    copay_notes: Optional[str] = None


class TpaCaseUpdateIn(BaseModel):
    status: str  # "pending" | "query_raised" | "approved" | "denied"
    authorized_amount: Optional[float] = None
    room_category_eligibility: Optional[str] = None
    copay_notes: Optional[str] = None
    query_notes: Optional[str] = None