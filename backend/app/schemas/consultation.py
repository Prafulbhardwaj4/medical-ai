from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List, Literal, Dict
from app.schemas.admission import RadiologyFormFIn

class MedicineItem(BaseModel):
    name: str
    brand_name: str = ""
    dosage: str
    frequency: str
    duration: str
    schedule: Literal["otc", "controlled"] = "controlled"
    times_per_day: Optional[float] = None
    duration_days: Optional[int] = None

class StructureRequest(BaseModel):
    transcript: Optional[str] = None

class ConsultationStructured(BaseModel):
    chief_complaint: Optional[str] = ""
    diagnosis: Optional[str] = ""
    vitals: Optional[Dict[str, str]] = {}
    medicines: Optional[List[MedicineItem]] = []
    tests: Optional[List[str]] = []
    recommended_test_ids: Optional[List[int]] = []  # real, orderable tests — same-day-return reopen flow adds NEW ones here; `tests` above stays just the display list
    test_priorities: Optional[Dict[int, str]] = {}
    recommended_radiology_template_ids: Optional[List[int]] = []  # real, orderable imaging studies — mirrors recommended_test_ids
    radiology_priorities: Optional[Dict[int, str]] = {}
    radiology_form_f: Optional[Dict[int, RadiologyFormFIn]] = {}  # keyed by radiology_template_id — PCPNDT Form F (item 7)
    clinical_indication: Optional[str] = None
    advice: Optional[str] = ""
    followup: Optional[str] = ""

class ConsultationOut(BaseModel):
    id: int
    token_number: Optional[str] = None
    patient_id: int
    doctor_id: int
    raw_transcript: Optional[str] = None
    chief_complaint: Optional[str] = None
    diagnosis: Optional[str] = None
    medicines: Optional[str] = None
    tests: Optional[str] = None
    advice: Optional[str] = None
    followup: Optional[str] = None
    nurse_instructions: Optional[str] = None
    has_pending_tests: bool
    pdf_path: Optional[str] = None
    whatsapp_status: str
    created_at: datetime

    class Config:
        from_attributes = True

class ConfirmPrescriptionPayload(BaseModel):
    recommended_test_ids: Optional[List[int]] = []
    test_priorities: Optional[Dict[int, str]] = {}
    recommended_radiology_template_ids: Optional[List[int]] = []
    radiology_priorities: Optional[Dict[int, str]] = {}
    radiology_form_f: Optional[Dict[int, RadiologyFormFIn]] = {}  # keyed by radiology_template_id — PCPNDT Form F (item 7)
    clinical_indication: Optional[str] = None

class ConsultationHistoryItem(BaseModel):
    id: int
    token_number: Optional[str]
    created_at: datetime
    chief_complaint: Optional[str]
    diagnosis: Optional[str]
    medicines: Optional[str]
    tests: Optional[str]
    advice: Optional[str]
    followup: Optional[str]
    whatsapp_status: str
    doctor_name: Optional[str] = None
    doctor_specialization: Optional[str] = None
    vitals: Optional[str] = None
    ordered_tests: Optional[str] = None
    medicine_statuses: Optional[Dict[str, str]] = {}
    test_statuses: Optional[Dict[str, str]] = {}
    ordered_radiology: Optional[str] = None
    radiology_statuses: Optional[Dict[str, str]] = {}

    class Config:
        from_attributes = True