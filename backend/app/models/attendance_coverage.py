from sqlalchemy import Column, Integer, ForeignKey
from app.database import Base

class AttendanceCoverage(Base):
    """One row per ward or doctor a nurse/assistant is covering for a given
    day's attendance record. A record can have any number of these — one row
    per ward_type_id and/or doctor_id selected when marking Present that day.
    Exactly one of ward_type_id / doctor_id is set per row. Existing
    doctor/receptionist/lab/pharmacy attendance (single room_id on
    AttendanceRecord) is untouched — this is additive, nurse/assistant only."""
    __tablename__ = "attendance_coverage"

    id = Column(Integer, primary_key=True, index=True)
    attendance_record_id = Column(Integer, ForeignKey("attendance_records.id", ondelete="CASCADE"), nullable=False, index=True)
    ward_type_id = Column(Integer, ForeignKey("admission_ward_types.id"), nullable=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)