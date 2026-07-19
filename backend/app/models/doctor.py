from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Enum, Float
from sqlalchemy.orm import relationship
from app.database import Base
from app.utils.timezone import now_ist_naive
import enum

class UserRole(enum.Enum):
    super_admin = "super_admin"
    admin = "admin"
    sub_admin = "sub_admin"
    doctor = "doctor"
    receptionist = "receptionist"
    nurse = "nurse"
    lab = "lab"
    pharmacy = "pharmacy"

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
    created_at = Column(DateTime, default=now_ist_naive)
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime, nullable=True)

    role = Column(Enum(UserRole, native_enum=False), default=UserRole.doctor, nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    consultation_fee = Column(Float, nullable=True)
    room_number = Column(String, nullable=True)

    patients = relationship("Patient", foreign_keys="Patient.created_by", back_populates="doctor")
    hospital = relationship("Hospital", backref="doctors")

    @property
    def hospital_type(self):
        return self.hospital.hospital_type if self.hospital else None

    @property
    def billing_enabled(self):
        return self.hospital.billing_enabled if self.hospital else False

    @property
    def default_consultation_fee(self):
        return self.hospital.default_consultation_fee if self.hospital else None