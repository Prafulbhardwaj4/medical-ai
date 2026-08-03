from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from app.database import Base
from app.utils.timezone import now_ist_naive


class AdmissionConsent(Base):
    """One record per signed consent — deliberately NOT a single blanket
    'consent given: yes/no' flag on Admission. Each consent type is
    independently signed and timestamped, and a type can be recorded more
    than once (e.g. a second procedure, a repeat transfusion). When the
    patient can't sign for themselves (minor/incapacitated), signer_name +
    relationship capture who signed on their behalf."""
    __tablename__ = "admission_consents"

    id = Column(Integer, primary_key=True, index=True)
    admission_id = Column(Integer, ForeignKey("admissions.id"), nullable=False)
    consent_type = Column(String, nullable=False)  # "general" | "procedure" | "anaesthesia" | "blood_transfusion" | "high_risk" | "lama_dama"
    signer_name = Column(String, nullable=False)  # patient's own name, or the guardian/next-of-kin's name
    signed_by_guardian = Column(Boolean, nullable=False, default=False)
    relationship = Column(String, nullable=True)  # e.g. "Father", "Spouse", "Legal Guardian" — required when signed_by_guardian is True
    witness_name = Column(String, nullable=True)  # independent witness, used for LAMA/DAMA where possible
    notes = Column(Text, nullable=True)  # e.g. which procedure, or a capacity-evaluation note for LAMA/DAMA
    recorded_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    signed_at = Column(DateTime, default=now_ist_naive)