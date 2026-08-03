from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class NotifiableDisease(Base):
    """Hospital-configurable IDSP notifiable-disease list — varies
    state-by-state, so this is never hardcoded (Phase 6 item 23)."""
    __tablename__ = "notifiable_diseases"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=now_ist_naive)