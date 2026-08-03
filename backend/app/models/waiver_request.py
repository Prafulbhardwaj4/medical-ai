from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class WaiverRequest(Base):
    """A discount/waiver against an in-progress OPD visit or IPD admission
    bill — never against an already-issued invoice, since that's a credit
    note's job (see CreditDebitNote). Small waivers under the hospital's
    configured cap/percent apply immediately (status="approved" straight
    away); larger ones sit here as "pending_approval" until an admin or
    manager resolves them. Exactly one of checkin_id / admission_id is set
    per request."""
    __tablename__ = "waiver_requests"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    checkin_id = Column(Integer, ForeignKey("checkins.id"), nullable=True)
    admission_id = Column(Integer, ForeignKey("admissions.id"), nullable=True)
    amount = Column(Float, nullable=False)
    reason = Column(String, nullable=False)
    status = Column(String, nullable=False, default="approved")  # "approved" | "pending_approval" | "rejected"
    requested_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    resolved_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    requested_at = Column(DateTime, default=now_ist_naive)
    resolved_at = Column(DateTime, nullable=True)
    charge_id = Column(Integer, nullable=True)  # id of the AdmissionCharge/OpdCharge row created once applied