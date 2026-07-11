from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from datetime import datetime
from app.database import Base

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    source_key = Column(String, nullable=False)  # e.g. "low_stock:42" — used to dedupe/update in place
    type = Column(String, nullable=False)
    severity = Column(String, nullable=False, default="warning")
    title = Column(String, nullable=False)
    message = Column(String, nullable=False)
    link_type = Column(String, nullable=True)
    link_id = Column(Integer, nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)