from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base

class Consultation(Base):
    __tablename__ = "consultations"

    id = Column(Integer, primary_key=True, index=True)
    token_number = Column(String, unique=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)

    raw_transcript = Column(Text, nullable=True)

    # AI-structured fields (stored as JSON strings)
    chief_complaint = Column(Text, nullable=True)
    diagnosis = Column(Text, nullable=True)
    medicines = Column(Text, nullable=True)       # JSON
    tests = Column(Text, nullable=True)           # JSON
    advice = Column(Text, nullable=True)
    followup = Column(Text, nullable=True)
    nurse_instructions = Column(Text, nullable=True)
    vitals = Column(Text, nullable=True)  # JSON: {bp, temperature, pulse, weight, spo2}
    recommended_test_ids = Column(Text, nullable=True)  # JSON list of TestCatalogItem ids
    is_voided = Column(Boolean, default=False)

    has_pending_tests = Column(Boolean, default=False)
    pdf_path = Column(String, nullable=True)
    whatsapp_status = Column(String, default="not_sent")  # not_sent / sent / failed
    verify_hash = Column(String, nullable=True, unique=True, index=True)
    is_dispensed = Column(Boolean, default=False)
    dispensed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="consultations")