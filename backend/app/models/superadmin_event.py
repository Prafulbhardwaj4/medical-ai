from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class SuperAdminEvent(Base):
    """A stored Super Admin notification (pilot cap reached, deadline day, grace over).
    `dedupe_key` is UNIQUE, so each event is stored once and never repeats.
    Seen state reuses SuperAdminAlertSeen (alert_key "pilot_event-<id>", marker = dedupe_key)."""
    __tablename__ = "superadmin_events"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False, index=True)
    dedupe_key = Column(String, nullable=False, unique=True, index=True)  # e.g. "pilot_cap:12:2026-11-01"
    event_type = Column(String, nullable=False)  # pilot_cap | pilot_deadline | pilot_grace_over
    severity = Column(String, nullable=False, default="warning")
    title = Column(String, nullable=False)
    message = Column(String, nullable=False)
    created_at = Column(DateTime, default=now_ist_naive, nullable=False)