from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from app.database import Base
from app.utils.timezone import now_ist_naive


class VisitFeedback(Base):
    """Lightweight post-consultation feedback tied to a specific visit —
    hospital-facing (visible to hospital staff), skippable."""
    __tablename__ = "visit_feedback"

    id = Column(Integer, primary_key=True, index=True)
    checkin_id = Column(Integer, ForeignKey("checkins.id"), unique=True, nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    rating = Column(Integer, nullable=False)  # 1-5
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=now_ist_naive)


class PortalSuggestion(Base):
    """General, freeform portal-facing suggestion box — not tied to any
    specific visit, skippable."""
    __tablename__ = "portal_suggestions"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("patient_accounts.id"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=now_ist_naive)