from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class ConsentRecord(Base):
    """Who agreed to / was informed of what, under which notice version, when, recorded by whom.
    subject_type: patient | portal_account | staff. purpose: portal_signup | ai_recording | hiv_test | terms | privacy.
    Notice TEXT lives in the frontend / legal documents (PENDING LEGAL REVIEW); only its version is stored here."""
    __tablename__ = "consent_records"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=True, index=True)
    subject_type = Column(String, nullable=False)
    subject_id = Column(Integer, nullable=False, index=True)
    purpose = Column(String, nullable=False)
    notice_version = Column(String, nullable=False)
    recorded_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    created_at = Column(DateTime, default=now_ist_naive)