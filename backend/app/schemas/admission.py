from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


VALID_ADMISSION_TYPES = {"planned", "emergency", "maternity", "transfer_in", "day_care"}


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
    admission_type: str = "planned"     # "planned" | "emergency" | "maternity" | "transfer_in" | "day_care"
    admission_date: Optional[str] = None  # ISO datetime string — reception can enter the actual admission date/time; defaults to now if not given


class UpdateDiagnosisIn(BaseModel):
    diagnosis: str


class EmergencyAdmitIn(BaseModel):
    name: Optional[str] = None
    approx_age: Optional[int] = None
    approx_gender: Optional[str] = None
    reason: str
    doctor_id: Optional[int] = None  # nullable — reception can submit with no doctor present yet (see admit_emergency)
    deposit_amount: float = 0
    deposit_payment_method: Optional[str] = None


class SendToAdmissionIn(BaseModel):
    patient_id: int
    reason: Optional[str] = None


VALID_WARD_CATEGORIES = {"general", "icu", "private", "maternity", "nicu", "isolation", "day_care", "other"}


class WardTypeCreateIn(BaseModel):
    name: str
    daily_charge: float
    default_deposit: float = 0
    is_icu: bool = False
    is_ot: bool = False
    ot_charge: Optional[float] = None
    category: str = "general"
    is_emergency_ward: bool = False
    # total_beds is no longer set directly here — a ward type's bed count is
    # the sum of its rooms (see RoomCreateIn below). New ward types start at
    # 0 beds until the admin adds rooms to them.


class RoomCreateIn(BaseModel):
    room_number: str
    beds_count: int


class RoomOut(BaseModel):
    id: int
    ward_type_id: int
    room_number: str
    beds_count: int

    class Config:
        from_attributes = True


class WardTypeOut(BaseModel):
    id: int
    name: str
    total_beds: int
    daily_charge: float
    default_deposit: float = 0
    is_icu: bool = False
    is_ot: bool = False
    ot_charge: Optional[float] = None
    category: str = "general"
    is_emergency_ward: bool = False
    occupied: int = 0
    vacant: int = 0
    rooms: List[RoomOut] = []

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
    units: int = 1  # strips/bottles/etc, whatever the medicine's dosage form makes a sensible dispensing unit
    manual_unit_price: Optional[float] = None  # per-strip/unit price — only used when medicine_id is None (not in catalog); billing itself happens later, at pharmacy dispense
    sourced_outside: bool = False  # patient/relatives sourcing this themselves — no stock deduction, no bill line


class AddChargeIn(BaseModel):
    charge_type: str  # "medicine" | "test" | "procedure" | "other"
    description: str
    amount: float
    quantity: int = 1


class ProfessionalFeeIn(BaseModel):
    amount: Optional[float] = None  # null clears the override, falling back to the doctor's default professional_fee_per_admission


VALID_CONSENT_TYPES = {"general", "procedure", "anaesthesia", "blood_transfusion", "high_risk", "lama_dama"}


class AdmissionConsentIn(BaseModel):
    consent_type: str
    signer_name: str
    signed_by_guardian: bool = False
    relationship: Optional[str] = None  # required if signed_by_guardian is True
    witness_name: Optional[str] = None
    notes: Optional[str] = None


class ReturnMedicationIn(BaseModel):
    quantity: int
    restock: bool = False  # deprecated — retained for backward compat, no longer increments stock
    disposition: str  # "returned_to_supplier" | "sent_to_disposal"
    note: Optional[str] = None


class EmergencyAlertIn(BaseModel):
    message: Optional[str] = None


class AddAdmissionTestIn(BaseModel):
    test_id: Optional[int] = None
    test_name: str
    price: float = 0
    priority: Optional[str] = "routine"  # "routine" | "urgent" | "stat" — Phase 3 item 5
    clinical_indication: Optional[str] = None  # e.g. "suspected DKA" — Phase 3 item 7
    order_batch_id: Optional[str] = None  # shared across every test submitted in the same "Order Test(s)" action


class RequestWardChangeIn(BaseModel):
    requested_ward_type_id: int
    note: Optional[str] = None


class ChangeWardIn(BaseModel):
    ward_type_id: int
    bed_number: str


VALID_DISCHARGE_TYPES = {"planned", "lama_dama", "death"}


class CollectBalanceIn(BaseModel):
    payment_method: str  # "cash" | "card" | "upi"


class DischargeIn(BaseModel):
    discharge_type: str = "planned"  # "planned" | "lama_dama" | "death"
    discharge_summary: Optional[str] = None
    refund_channel: Optional[str] = None  # "cash" | "card" | "upi" | "online", required when the deposit exceeds charges
    # LAMA/DAMA only
    capacity_evaluation_note: Optional[str] = None  # only needed if there's any question of impaired decision-making
    # Death-in-hospital only
    time_of_death: Optional[str] = None  # ISO datetime string
    certifying_doctor_id: Optional[int] = None
    cause_of_death: Optional[str] = None
    is_mlc: Optional[bool] = None  # Medico-Legal Case — whether police/forensic involvement is required before body release
    # Structured discharge summary (NABH-standard fields) — discharge_summary
    # above remains the free-text "additional notes" catch-all
    discharging_doctor_id: Optional[int] = None  # defaults to the admission's admitting_doctor_id if not given
    course_in_hospital: Optional[str] = None
    procedures_performed: Optional[str] = None
    discharge_diagnosis: Optional[str] = None
    condition_at_discharge: Optional[str] = None
    medications_on_discharge: Optional[str] = None
    follow_up_instructions: Optional[str] = None


class TopupRequestIn(BaseModel):
    requested_amount: float
    reason: Optional[str] = None


class CollectTopupIn(BaseModel):
    payment_method: str  # "cash" | "card" | "upi"


class TpaCaseIn(BaseModel):
    insurer_name: str
    policy_number: Optional[str] = None
    room_category_eligibility: Optional[str] = None
    eligible_daily_rate: Optional[float] = None  # numeric ₹/day — used to compute the proportionate deduction estimate
    copay_notes: Optional[str] = None


class TpaCaseUpdateIn(BaseModel):
    status: str  # "pending" | "query_raised" | "approved" | "denied"
    authorized_amount: Optional[float] = None
    room_category_eligibility: Optional[str] = None
    eligible_daily_rate: Optional[float] = None
    copay_notes: Optional[str] = None
    query_notes: Optional[str] = None


class TpaSettleIn(BaseModel):
    settled_amount: float
    settlement_notes: Optional[str] = None


class ProgressNoteIn(BaseModel):
    note: str