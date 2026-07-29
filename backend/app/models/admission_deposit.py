from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class AdmissionDeposit(Base):
    """Ledger of every deposit contribution for an admission — the initial
    deposit at admission, plus every collected top-up. Sum of these rows is
    the running deposit total the accruing bill is measured against."""
    __tablename__ = "admission_deposits"

    id = Column(Integer, primary_key=True, index=True)
    admission_id = Column(Integer, ForeignKey("admissions.id"), nullable=False)
    amount = Column(Float, nullable=False)
    payment_method = Column(String, nullable=False)  # "cash" | "card" | "upi"
    note = Column(String, nullable=True)
    collected_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    collected_at = Column(DateTime, default=now_ist_naive)


class AdmissionDepositTopupRequest(Base):
    """A trackable request to top up the deposit mid-stay — visible to
    reception and (later) the patient portal, instead of an informal ask
    that never makes it into the record."""
    __tablename__ = "admission_deposit_topup_requests"

    id = Column(Integer, primary_key=True, index=True)
    admission_id = Column(Integer, ForeignKey("admissions.id"), nullable=False)
    requested_amount = Column(Float, nullable=False)
    reason = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")  # pending | collected | cancelled
    requested_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    requested_at = Column(DateTime, default=now_ist_naive)
    deposit_id = Column(Integer, ForeignKey("admission_deposits.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)