from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base
import enum

class UserRole(enum.Enum):
    super_admin = "super_admin"
    admin = "admin"
    sub_admin = "sub_admin"
    doctor = "doctor"
    receptionist = "receptionist"
    nurse = "nurse"

class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False, default="Dr.")
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    phone = Column(String, nullable=False)
    specialization = Column(String, nullable=False)
    registration_number = Column(String, nullable=True)
    clinic_name = Column(String, nullable=True)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime, nullable=True)

    role = Column(Enum(UserRole), default=UserRole.doctor, nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)

    patients = relationship("Patient", foreign_keys="Patient.created_by", back_populates="doctor")
    hospital = relationship("Hospital", backref="doctors")

    @property
    def hospital_type(self):
        return self.hospital.hospital_type if self.hospital else None