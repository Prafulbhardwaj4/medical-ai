from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Index
from app.database import Base
from app.utils.timezone import now_ist_naive


class StaffResetCode(Base):
    """One forgot-password code for a staff or hospital-admin account. Only a keyed hash (HMAC) of the
    6-digit code is stored here. The readable code exists only in the encrypted column of its
    WhatsApp message, and is deleted when the code is used or expires. All times are naive IST."""
    __tablename__ = "staff_reset_codes"
    __table_args__ = (Index("ix_staff_reset_codes_doctor_created", "doctor_id", "created_at"),)

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    code_hash = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)  # 10 minutes after it was made
    attempts = Column(Integer, nullable=False, default=0)  # tries counted; 5 at most
    used = Column(Boolean, nullable=False, default=False)  # single use; a newer code also sets this on the older ones
    created_at = Column(DateTime, nullable=False, default=now_ist_naive)