from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class SubscriptionPayment(Base):
    """One row per confirmed subscription payment (created by Renew). Gives real
    revenue, overdue lists and ARR instead of a list-price estimate."""
    __tablename__ = "subscription_payments"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)
    tier = Column(String, nullable=False)
    billing_period = Column(String, nullable=False, default="monthly")  # monthly | yearly
    amount = Column(Float, nullable=False)
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    collected_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    note = Column(String, nullable=True)
    created_at = Column(DateTime, default=now_ist_naive)