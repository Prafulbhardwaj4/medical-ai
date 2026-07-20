import enum
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Enum, UniqueConstraint, Text
)
from sqlalchemy.orm import relationship
from app.database import Base
from app.utils.timezone import now_ist_naive


class AppointmentStatus(str, enum.Enum):
    booked = "booked"
    confirmed = "confirmed"
    completed = "completed"
    cancelled = "cancelled"
    no_show = "no_show"


class AppointmentType(str, enum.Enum):
    scheduled = "scheduled"     # future date/time booking
    queue_home = "queue_home"   # remote token reservation, same/future day


class PatientAccount(Base):
    """Portal login identity. Distinct from Patient (which is one hospital's
    walk-in record). One account can link to many Patient rows across hospitals."""
    __tablename__ = "patient_accounts"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, unique=True, nullable=True, index=True)
    password_hash = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_ist_naive)

    profiles = relationship("PatientProfileLink", back_populates="account", cascade="all, delete-orphan")
    appointments = relationship("Appointment", back_populates="account", cascade="all, delete-orphan")


class PatientProfileLink(Base):
    """Links a portal account to one real Patient row. First one created at
    signup; more added via the tap-to-confirm flow on later visits."""
    __tablename__ = "patient_profile_links"
    __table_args__ = (UniqueConstraint("patient_id", name="uq_profile_link_patient"),)

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("patient_accounts.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    relation = Column(String, default="self", nullable=False)  # "self" | "family"
    linked_at = Column(DateTime, default=now_ist_naive)

    account = relationship("PatientAccount", back_populates="profiles")
    patient = relationship("Patient")


class InviteStatus(Base):
    """One-time-ever invite flag per phone number. Never resend once True."""
    __tablename__ = "portal_invite_status"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String, unique=True, nullable=False, index=True)
    invited = Column(Boolean, default=False)
    invited_at = Column(DateTime, nullable=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True)


class OTPCode(Base):
    __tablename__ = "portal_otp_codes"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String, nullable=False, index=True)
    code_hash = Column(String, nullable=False)
    purpose = Column(String, nullable=False)  # "signup" | "login"
    expires_at = Column(DateTime, nullable=False)
    consumed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now_ist_naive)


class Appointment(Base):
    __tablename__ = "portal_appointments"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("patient_accounts.id"), nullable=False)
    profile_link_id = Column(Integer, ForeignKey("patient_profile_links.id"), nullable=True)

    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    slot_id = Column(Integer, ForeignKey("doctor_slots.id"), nullable=True)

    type = Column(Enum(AppointmentType), nullable=False)
    requested_time = Column(DateTime, nullable=False)
    status = Column(Enum(AppointmentStatus), default=AppointmentStatus.booked)
    payment_status = Column(String, default="unpaid", nullable=False)  # unpaid | paid
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=now_ist_naive)

    account = relationship("PatientAccount", back_populates="appointments")
    profile_link = relationship("PatientProfileLink")