from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Index
from app.database import Base
from app.utils.timezone import now_ist_naive


class WhatsappMessage(Base):
    """One prepared WhatsApp message. Staff copy it by hand until the automatic sender
    exists (see app/services/whatsapp_messages.py). All times are naive IST."""
    __tablename__ = "whatsapp_messages"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=True)  # NULL = super-admin-level message

    recipient_kind = Column(String, nullable=False, default="patient")  # staff | patient | portal_account | sample
    recipient_id = Column(Integer, nullable=True)
    recipient_name = Column(String, nullable=False)
    recipient_role = Column(String, nullable=False)
    recipient_phone = Column(String, nullable=False)  # real number, normalized by utils/phone.py

    template_key = Column(String, nullable=False)
    message_text = Column(Text, nullable=False)  # exact text to send; for secret messages the secret is masked with dots
    is_secret = Column(Boolean, nullable=False, default=False)
    secret_enc = Column(Text, nullable=True)  # Fernet-encrypted full text of a secret message; NULL once wiped
    visibility = Column(String, nullable=False, default="all")  # all | admin_super | super_only

    status = Column(String, nullable=False, default="pending")  # scheduled | due | pending | sent | expired | cancelled
    prev_status = Column(String, nullable=True)  # set by mark-sent / cancel so Undo can restore it
    status_changed_at = Column(DateTime, nullable=True)
    due_at = Column(DateTime, nullable=False, default=now_ist_naive)
    expires_at = Column(DateTime, nullable=True)
    is_sample = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, nullable=False, default=now_ist_naive)
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    sent_marked_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    sent_marked_at = Column(DateTime, nullable=True)

    appointment_id = Column(Integer, nullable=True, index=True)
    checkin_id = Column(Integer, nullable=True, index=True)
    token_number = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_whatsapp_messages_hospital_status_due", "hospital_id", "status", "due_at"),
    )