from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class HospitalLead(Base):
    """A patient telling us their hospital isn't on MedScribe yet, from the
    'Can't find your hospital?' link in the booking wizard's hospital-select
    step. Feeds the super admin's Hospital Leads tab so sales can follow up
    and onboard that hospital — a business-development lead, deliberately
    separate from UpgradeRequest (which is an existing paying hospital)."""
    __tablename__ = "hospital_leads"

    id = Column(Integer, primary_key=True, index=True)
    patient_account_id = Column(Integer, ForeignKey("patient_accounts.id"), nullable=False)
    contact_phone = Column(String, nullable=False)
    state = Column(String, nullable=False)
    city = Column(String, nullable=False)
    hospital_name = Column(String, nullable=False)
    location = Column(String, nullable=True)
    note = Column(Text, nullable=True)
    status = Column(String, default="new", nullable=False)  # new | contacted | converted | closed
    follow_up_notes = Column(Text, nullable=True)
    owner = Column(String, nullable=True)
    next_follow_up_at = Column(DateTime, nullable=True)
    contacted_at = Column(DateTime, nullable=True)
    converted_hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=True)
    created_at = Column(DateTime, default=now_ist_naive, nullable=False)