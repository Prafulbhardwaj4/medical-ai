from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from app.database import Base
from app.utils.timezone import now_ist_naive

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    actor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    actor_name = Column(String, nullable=False)
    actor_role = Column(String, nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=True)

    action = Column(String, nullable=False, index=True)
    target_type = Column(String, nullable=False, index=True)
    target_id = Column(Integer, nullable=True)
    target_label = Column(String, nullable=True)

    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=now_ist_naive, nullable=False, index=True)