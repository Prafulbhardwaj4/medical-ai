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
    assistant = "assistant"
    lab = "lab"
    pharmacy = "pharmacy"
    radiology = "radiology"

class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    doctor_uid = Column(String, unique=True, nullable=True, index=True)  # hospital-initials + hash, e.g. MEDS-A1B2C3
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
    is_hiv_authorized = Column(Boolean, default=False, nullable=False)  # explicitly granted by admin — tighter access than the general "lab" role (Phase 6 item 21)

    role = Column(Enum(UserRole, native_enum=False), default=UserRole.doctor, nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    consultation_fee = Column(Float, nullable=True)
    professional_fee_per_admission = Column(Float, nullable=True)  # visiting/empanelled consultant's own fee for IPD care — distinct from the OPD consultation_fee and from the hospital's facility/room charges; blank = not applicable (e.g. in-house/salaried doctor)
    visit_fee = Column(Float, nullable=True)
    room_number = Column(String, nullable=True)
    active_consultation_id = Column(Integer, ForeignKey("consultations.id"), nullable=True)  # unconfirmed draft this doctor is currently mid-session with, if any — kept in sync by consultations.py so an emergency interrupt always resumes the *right* draft, never a guess

    patients = relationship("Patient", foreign_keys="Patient.created_by", back_populates="doctor")
    hospital = relationship("Hospital", backref="doctors")

    @property
    def hospital_type(self):
        return self.hospital.hospital_type if self.hospital else None

    @property
    def billing_enabled(self):
        return self.hospital.billing_enabled if self.hospital else False

    @property
    def hospital_tier(self):
        return self.hospital.tier if self.hospital else "growth"

    @property
    def default_consultation_fee(self):
        return self.hospital.default_consultation_fee if self.hospital else None