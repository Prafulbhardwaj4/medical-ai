from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class Refund(Base):
    """Refund record — cash/QR refunds are recorded complete immediately;
    online/portal refunds settle automatically through the gateway (48-72h)
    and are tracked as 'pending' until confirmed. Covers every refund
    scenario (appointment, pharmacy, IPD deposit balance, TPA overpayment)
    uniformly, per Receptionist Flow §8."""
    __tablename__ = "refunds"

    id = Column(Integer, primary_key=True, index=True)
    # Nullable: a system-generated refund (patient self-cancel, auto-decline)
    # has no staff actor and may predate the patient ever getting a real
    # Patient row created by reception.
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    source_type = Column(String, nullable=False)  # appointment | pharmacy | ipd_deposit | opd_charge | tpa | other
    source_id = Column(Integer, nullable=True)
    amount = Column(Float, nullable=False)
    channel = Column(String, nullable=False)  # cash | card | upi | online
    status = Column(String, nullable=False, default="completed")  # completed | pending
    reason = Column(String, nullable=True)
    processed_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)  # null = system-generated, no staff actor
    processed_at = Column(DateTime, default=now_ist_naive)