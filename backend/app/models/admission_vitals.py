from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class AdmissionVitals(Base):
    """A nurse's timestamped vitals reading during an inpatient stay. Unlike
    OPD vitals (one JSON blob on Checkin, overwritten/merged), IPD vitals are
    taken repeatedly through a stay, so each reading is its own row — a log,
    same pattern as AdmissionProgressNote."""
    __tablename__ = "admission_vitals"

    id = Column(Integer, primary_key=True, index=True)
    admission_id = Column(Integer, ForeignKey("admissions.id"), nullable=False)
    recorded_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    data = Column(Text, nullable=False)  # JSON: {"BP": "120/80", "Pulse": "78", ...}
    recorded_at = Column(DateTime, default=now_ist_naive)