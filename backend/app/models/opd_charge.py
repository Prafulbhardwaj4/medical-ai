from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class OpdCharge(Base):
    """An ad-hoc OPD charge (dressing, injection, etc.) added during/after a
    consultation — goes straight onto the visit's bill, no approval gate.
    Mirrors AdmissionCharge's role for IPD, scoped to a single OPD visit."""
    __tablename__ = "opd_charges"

    id = Column(Integer, primary_key=True, index=True)
    checkin_id = Column(Integer, ForeignKey("checkins.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    description = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    added_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)  # nullable for system-generated charges (e.g. a reschedule fee difference applied at online check-in, no staff actor involved) — mirrors Checkin.created_by's same "system handoff" pattern
    status = Column(String, nullable=False, default="payment_pending")  # payment_pending | paid
    payment_method = Column(String, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    charged_at = Column(DateTime, default=now_ist_naive)