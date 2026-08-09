from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    staff_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)   # identifies the admin<->staff thread
    sender_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)  # who actually wrote this message
    recipient_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)  # set only for peer-to-peer (staff<->staff) messages; NULL means this is an admin-thread message
    body = Column(Text, nullable=False)
    is_read_by_staff = Column(Boolean, default=False, nullable=False)
    is_read_by_admin = Column(Boolean, default=False, nullable=False)
    attachment_filename = Column(String, nullable=True)  # name on disk (uuid-based, unguessable)
    attachment_name = Column(String, nullable=True)       # original filename, for display/download
    attachment_type = Column(String, nullable=True)       # "image" | "file"
    created_at = Column(DateTime, default=now_ist_naive, nullable=False)