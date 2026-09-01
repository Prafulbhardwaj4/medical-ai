import enum
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Enum, UniqueConstraint, Text, Float
)
from sqlalchemy.orm import relationship
from app.database import Base
from app.utils.timezone import now_ist_naive


class AppointmentStatus(str, enum.Enum):
    booked = "booked"
    pending_review = "pending_review"  # hospital-side approval needed — see Phase 1 item 3
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
    address = Column(String, nullable=True)  # saved default address, used unless a booking opts for a different one
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_ist_naive)

    profiles = relationship("PatientProfileLink", back_populates="account", cascade="all, delete-orphan")
    appointments = relationship("Appointment", back_populates="account", cascade="all, delete-orphan", foreign_keys="[Appointment.account_id]")


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


class CrossBookingRequest(Base):
    """A patient asking to book an appointment for a family member who has
    their OWN separate portal account, rather than creating a new profile
    under this account. No WhatsApp yet, so 'sending an OTP' isn't possible —
    instead the target account sees and confirms this the next time they
    open their own portal, same pattern as the pending-confirmation profile
    flow (Phase 1 item 3)."""
    __tablename__ = "cross_booking_requests"

    id = Column(Integer, primary_key=True, index=True)
    requesting_account_id = Column(Integer, ForeignKey("patient_accounts.id"), nullable=False)
    target_account_id = Column(Integer, ForeignKey("patient_accounts.id"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    slot_id = Column(Integer, ForeignKey("doctor_slots.id"), nullable=True)
    type = Column(String, nullable=False)  # "scheduled" | "queue_home"
    notes = Column(String, nullable=True)
    address = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")  # pending | confirmed | rejected
    created_at = Column(DateTime, default=now_ist_naive)


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


class PatientAddress(Base):
    """One of possibly several saved addresses for an account (item 53) —
    PatientAccount.address stays in sync with whichever row is is_default,
    so existing single-address consumers keep working unchanged."""
    __tablename__ = "patient_addresses"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("patient_accounts.id"), nullable=False)
    label = Column(String, nullable=False, default="Address")
    address = Column(String, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
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
    payment_method = Column(String, nullable=True)  # "cash" | "card" | "upi" — how reception collected the consultation fee
    paid_at = Column(DateTime, nullable=True)  # exact collection moment — propagated onto the Checkin so day-end buckets it on the right day
    notes = Column(Text, nullable=True)
    address = Column(String, nullable=True)  # snapshot of the address used for this booking
    new_patient_name = Column(String, nullable=True)    # captured only when booking with no existing hospital record
    new_patient_gender = Column(String, nullable=True)
    new_patient_age = Column(Integer, nullable=True)
    new_patient_blood_group = Column(String, nullable=True)  # optional
    fee_amount = Column(Float, nullable=True)  # snapshot of what was actually paid, taken at mark-paid time
    review_deadline_at = Column(DateTime, nullable=True)          # set when status -> pending_review
    review_followup_sent_at = Column(DateTime, nullable=True)     # set once the first follow-up alert fires
    arrived_at = Column(DateTime, nullable=True)  # set when patient/reception marks arrival — drives grace-window + queue priority (Phase 2 item 7)

    # No-show / late handling + reschedule requests (Phase 3 item 8).
    no_show_detected_at = Column(DateTime, nullable=True)          # set once 1hr-past-slot threshold crosses with no consultation
    no_show_reason = Column(String, nullable=True)                 # "hospital_delay" | "patient_no_show" — patient's MCQ answer
    no_show_reschedule_deadline = Column(DateTime, nullable=True)  # requested_time + 72h once a reason is given
    reschedule_kind = Column(String, nullable=True)                # "no_show" | "same_day" — tags an in-flight pending_review request so accept/decline/expiry know which rules apply
    requested_reschedule_slot_id = Column(Integer, ForeignKey("doctor_slots.id"), nullable=True)

    # Mass reschedule (Phase 3 item 9) — set when the doctor is marked
    # unavailable and staff trigger the reschedule notice for this specific
    # affected booking. Self-serve: patient picks any new slot with the
    # SAME doctor, no reception approval needed (the hospital already
    # caused this), already-paid fee just carries over.
    mass_reschedule_notice = Column(Boolean, nullable=False, default=False)

    requested_by_account_id = Column(Integer, ForeignKey("patient_accounts.id"), nullable=True)  # set when a family member arranged this via cross-account booking (item 11)

    reschedule_balance_due = Column(Float, nullable=True)  # set when accept_appointment reschedules to a COSTLIER doctor — no live payment gateway to charge this online, so it's collected at check-in like any other OPD balance (see convert_appointment_to_checkin)

    created_at = Column(DateTime, default=now_ist_naive)

    account = relationship("PatientAccount", back_populates="appointments", foreign_keys=[account_id])
    profile_link = relationship("PatientProfileLink")