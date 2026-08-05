from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class AdmissionProgressNote(Base):
    """A doctor's dated clinical note during an inpatient stay — the daily
    round record. Distinct from the discharge summary (written once, at
    the very end) and from vitals (a different clinical voice)."""
    __tablename__ = "admission_progress_notes"

    id = Column(Integer, primary_key=True, index=True)
    admission_id = Column(Integer, ForeignKey("admissions.id"), nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    note = Column(Text, nullable=False)
    created_at = Column(DateTime, default=now_ist_naive)