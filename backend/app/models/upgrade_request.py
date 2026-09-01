from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class UpgradeRequest(Base):
    """A hospital admin's actual request to buy a higher tier — distinct
    from the internal staff-to-admin nudge, which is just a Notification
    and never creates one of these. This is what feeds the super admin's
    Upgrade Requests tab so a real person follows up and closes the sale."""
    __tablename__ = "upgrade_requests"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    requested_by_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    requested_tier = Column(String, nullable=False)  # tier key, e.g. "growth"
    message = Column(Text, nullable=True)
    contact_name = Column(String, nullable=False)
    contact_phone = Column(String, nullable=False)
    contact_email = Column(String, nullable=False)
    status = Column(String, default="new", nullable=False)  # new | contacted
    created_at = Column(DateTime, default=now_ist_naive, nullable=False)