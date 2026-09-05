from typing import Optional
from pydantic import BaseModel

VALID_REFERRAL_STATUSES = {"pending", "rejected", "departed", "admitted", "expired"}


class InitiateReferralIn(BaseModel):
    to_hospital_id: int
    clinical_note: str  # mandatory — diagnosis, reason for referral, urgency


class RejectReferralIn(BaseModel):
    rejection_note: str  # mandatory on every reject, at every tier


class RejectAndForwardIn(BaseModel):
    rejection_note: str  # mandatory reject note for the hop being rejected
    to_hospital_id: int  # the third hospital (C) being forwarded to
    clinical_note: str  # mandatory note for the new forwarded referral


class ReferralOut(BaseModel):
    id: int
    chain_id: int
    from_hospital_id: int
    from_hospital_name: str
    to_hospital_id: int
    to_hospital_name: str
    initiation_type: str
    patient_name: str
    patient_age: Optional[int] = None
    patient_gender: Optional[str] = None
    clinical_note: str
    diagnosis_snapshot: Optional[str] = None
    status: str
    acknowledged_at: Optional[str] = None
    rejected_at: Optional[str] = None
    rejection_note: Optional[str] = None
    departed_at: Optional[str] = None
    admitted_at: Optional[str] = None
    admitted_admission_id: Optional[int] = None
    expires_at: str
    created_at: str

    class Config:
        from_attributes = True