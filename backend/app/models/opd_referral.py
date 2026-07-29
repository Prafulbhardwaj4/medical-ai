from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class OpdReferral(Base):
    """A doctor referring a patient to another doctor within the same OPD visit —
    separate from AdmissionReferral (IPD-only, no specific target doctor).
    Creates a linked Checkin for the receiving doctor so the patient flows
    through their normal queue, tagged as a referral rather than a cold walk-in."""
    __tablename__ = "opd_referrals"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    referring_doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    referred_to_doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    checkin_id = Column(Integer, ForeignKey("checkins.id"), nullable=True)  # the linked checkin created for the receiving doctor
    note = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="pending")  # pending -> consulted (flipped on confirm) | cancelled
    created_at = Column(DateTime, default=now_ist_naive)