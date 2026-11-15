from sqlalchemy import Column, Integer, String, DateTime, ForeignKey

from app.database import Base
from app.utils.timezone import now_ist_naive


class SuperAdminEnrolmentCode(Base):
    """One-time code that must be entered before a super admin can enrol 2FA for the first time.
    Only the SHA-256 hash is stored. Single use, bound to one account, expires 24 hours after it is issued."""
    __tablename__ = "superadmin_enrolment_codes"

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False, index=True)
    code_hash = Column(String(64), nullable=False)
    expires_at = Column(DateTime, nullable=False)   # IST naive
    claimed_at = Column(DateTime, nullable=True)    # set when the code was entered correctly at /auth/totp/setup
    used_at = Column(DateTime, nullable=True)       # set when 2FA enrolment was confirmed (code is spent)
    created_at = Column(DateTime, default=now_ist_naive, nullable=False)