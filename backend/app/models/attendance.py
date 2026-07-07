from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, UniqueConstraint, Integer as Int
from datetime import datetime
from app.database import Base

class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (UniqueConstraint('doctor_id', 'date', name='uq_attendance_doctor_date'),)

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    date = Column(Date, nullable=False, index=True)
    status = Column(String, nullable=False, default="present")  # present / on_break / absent
    marked_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    room_number = Column(String, nullable=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)