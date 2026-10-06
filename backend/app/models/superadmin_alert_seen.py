from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class SuperAdminAlertSeen(Base):
    """A computed alert (hospital hit its limit / billing cycle ending) the super admin
    has dismissed. `marker` identifies WHICH occurrence was dismissed (cycle start or
    cycle end), so the alert comes back in the next billing cycle."""
    __tablename__ = "superadmin_alert_seen"

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    alert_key = Column(String, nullable=False, index=True)  # e.g. "hospital_limit-3"
    marker = Column(String, nullable=False)
    created_at = Column(DateTime, default=now_ist_naive, nullable=False)