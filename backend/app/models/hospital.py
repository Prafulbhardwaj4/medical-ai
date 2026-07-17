from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, Text
from app.database import Base
from app.utils.timezone import now_ist_naive

class Hospital(Base):
    __tablename__ = "hospitals"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    address = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    hospital_code = Column(String, unique=True, index=True, nullable=False)
    hospital_type = Column(String, default="private", nullable=False)
    billing_enabled = Column(Boolean, default=True, nullable=False)
    default_consultation_fee = Column(Float, nullable=True)
    gstin = Column(String, nullable=True)  # optional — hospital adds this later if/when they need GST on invoices
    phone = Column(String, nullable=True)  # optional — shown on PDF letterheads if set
    logo_base64 = Column(Text, nullable=True)  # optional — full data URI; stored in-DB since Render's disk is ephemeral
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_ist_naive)