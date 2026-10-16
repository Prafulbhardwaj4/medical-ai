from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
from app.database import Base
from app.utils.timezone import now_ist_naive


class HospitalUsageSnapshot(Base):
    """One ENDED window (calendar month or anchor-based billing cycle) of consultation counts.
    Written once, never updated, so past figures survive later edits to consultations."""
    __tablename__ = "hospital_usage_snapshots"
    __table_args__ = (UniqueConstraint("hospital_id", "period_kind", "period_start", name="uq_usage_snapshot_period"),)

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)
    period_kind = Column(String, nullable=False)  # "month" | "cycle"
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)  # exclusive
    completed_consultations = Column(Integer, nullable=False, default=0)
    ai_scribe_consultations = Column(Integer, nullable=False, default=0)  # subset of completed that consumed an AI Scribe credit
    tier = Column(String, nullable=True)  # tier when the window was stored
    billing_period = Column(String, nullable=True)  # monthly/yearly when stored
    finalized_at = Column(DateTime, default=now_ist_naive)