from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base
from app.utils.timezone import now_ist_naive

class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    patient_uid = Column(String, unique=True, index=True)
    url_token = Column(String, unique=True, index=True, nullable=False)
    abha_number = Column(String, nullable=True)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    age = Column(Integer, nullable=False)
    blood_group = Column(String, nullable=True)
    gender = Column(String, nullable=False)
    address = Column(String, nullable=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    created_at = Column(DateTime, default=now_ist_naive)

    doctor = relationship("Doctor", foreign_keys=[created_by], back_populates="patients")
    hospital = relationship("Hospital")
    consultations = relationship("Consultation", back_populates="patient")