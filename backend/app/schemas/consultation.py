from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List, Literal, Dict

class MedicineItem(BaseModel):
    name: str
    brand_name: str = ""
    dosage: str
    frequency: str
    duration: str
    schedule: Literal["otc", "controlled"] = "controlled"

class StructureRequest(BaseModel):
    transcript: Optional[str] = None

class ConsultationStructured(BaseModel):
    chief_complaint: Optional[str] = ""
    diagnosis: Optional[str] = ""
    vitals: Optional[Dict[str, str]] = {}
    medicines: Optional[List[MedicineItem]] = []
    tests: Optional[List[str]] = []
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

    class Config:
        from_attributes = True