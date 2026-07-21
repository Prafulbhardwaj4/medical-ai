from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, UniqueConstraint
from app.database import Base
from app.utils.timezone import now_ist_naive


class DoctorAvailabilityTemplate(Base):
    """The doctor's standing weekly availability pattern — persists until
    manually changed. Actual bookable DoctorSlot rows are (re)generated from
    this whenever it's saved."""
    __tablename__ = "doctor_availability_templates"

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), unique=True, nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    weekdays = Column(String, nullable=False, default="[0,1,2,3,4,5]")       # JSON list, 0=Mon
    morning_times = Column(String, nullable=False, default="[]")             # JSON list of "HH:MM"
    afternoon_times = Column(String, nullable=False, default="[]")
    evening_times = Column(String, nullable=False, default="[]")
    capacity_mode = Column(String, nullable=False, default="same")           # "same" | "per_period"
    capacity_same = Column(Integer, nullable=False, default=1)
    capacity_morning = Column(Integer, nullable=False, default=1)
    capacity_afternoon = Column(Integer, nullable=False, default=1)
    capacity_evening = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime, default=now_ist_naive, onupdate=now_ist_naive)


class DoctorUnavailability(Base):
    """A doctor marked absent/unavailable for a specific date. Blocks new
    bookings for that date; existing paid appointments are surfaced to
    staff for manual handling rather than auto-cancelled."""
    __tablename__ = "doctor_unavailability"
    __table_args__ = (UniqueConstraint("doctor_id", "date", name="uq_doctor_unavailable_date"),)

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    date = Column(Date, nullable=False, index=True)
    reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=now_ist_naive)