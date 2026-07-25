from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class AdmissionReferral(Base):
    """A doctor's decision that a patient needs to be admitted. Reception's
    '+ Admit' list is now driven entirely from these — reception no longer
    decides who gets admitted, only processes what a doctor already sent."""
    __tablename__ = "admission_referrals"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    referred_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    reason = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="pending")  # "pending" | "admitted" | "cancelled"
    created_at = Column(DateTime, default=now_ist_naive)