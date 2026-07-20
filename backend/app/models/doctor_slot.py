from sqlalchemy import Column, Integer, String, Date, Boolean, DateTime, ForeignKey, UniqueConstraint
from app.database import Base
from app.utils.timezone import now_ist_naive


class DoctorSlot(Base):
    __tablename__ = "doctor_slots"
    __table_args__ = (UniqueConstraint("doctor_id", "slot_date", "slot_time", name="uq_doctor_slot"),)

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    slot_date = Column(Date, nullable=False, index=True)
    slot_time = Column(String, nullable=False)   # "09:30" 24h
    period = Column(String, nullable=False)      # morning | afternoon | evening
    is_booked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=now_ist_naive)