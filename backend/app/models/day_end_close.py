from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import expression
from app.database import Base
from app.utils.timezone import now_ist_naive


class DayEndClose(Base):
    """One shift-close reconciliation record per hospital per day — system-logged
    totals by mode vs what reception actually counted in hand (Receptionist Flow §9)."""
    __tablename__ = "day_end_closes"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    close_date = Column(Date, nullable=False)
    system_cash = Column(Float, nullable=False, default=0)
    system_card = Column(Float, nullable=False, default=0)
    system_upi = Column(Float, nullable=False, default=0)
    # NULL = nobody counted the cash (auto-closed day). Variance is unknown, not zero.
    counted_cash = Column(Float, nullable=True)
    counted_card = Column(Float, nullable=True)
    counted_upi = Column(Float, nullable=True)
    auto_closed = Column(Boolean, nullable=False, default=False, server_default=expression.false())  # True = closed by the scheduler / catch-up, "not counted"
    notes = Column(String, nullable=True)
    closed_by = Column(Integer, ForeignKey("doctors.id"), nullable=True) 
    closed_at = Column(DateTime, default=now_ist_naive)