from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive

class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    checkin_id = Column(Integer, ForeignKey("checkins.id"), nullable=False, unique=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    items_json = Column(Text, nullable=False)  # [{type, name, qty, unit_price, line_total}]
    grand_total = Column(Float, nullable=False)
    generated_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    generated_from = Column(String, nullable=True)  # "reception" or "pharmacy"
    pdf_path = Column(String, nullable=True)
    generated_at = Column(DateTime, default=now_ist_naive)