from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class Suggestion(Base):
    """Free-text suggestion from any staff member, routed to Super Admin's
    dashboard. Staff can only see their own submissions and only read the
    status — they never see or set status themselves."""
    __tablename__ = "suggestions"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    hospital_name = Column(String, nullable=False)  # snapshot at submission time — stays correct even if the hospital is later renamed
    submitted_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    submitted_by_name = Column(String, nullable=False)  # snapshot
    submitted_by_role = Column(String, nullable=False)  # snapshot
    message = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="sent")  # "sent" | "seen" | "in_progress" | "rejected" | "completed"
    rejection_reason = Column(Text, nullable=True)  # only set when status == "rejected"
    resolved_by = Column(Integer, nullable=True)  # super admin's own id (not a doctors.id — separate auth), stored loosely
    follow_up_requested_at = Column(DateTime, nullable=True)  # staff tapped "Follow Up" — cleared whenever status changes or the message is edited
    created_at = Column(DateTime, default=now_ist_naive)
    updated_at = Column(DateTime, default=now_ist_naive, onupdate=now_ist_naive)