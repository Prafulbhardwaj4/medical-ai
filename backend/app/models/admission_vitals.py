from sqlalchemy import Column, Integer, Text, DateTime, Boolean, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class AdmissionVitals(Base):
    """A nurse's timestamped vitals reading during an inpatient stay. Unlike
    OPD vitals (one JSON blob on Checkin, overwritten/merged), IPD vitals are
    taken repeatedly through a stay, so each reading is its own row — a log,
    same pattern as AdmissionProgressNote. data is keyed by the locked
    IPD_STANDARD_VITALS labels from admission-detail.html (e.g. "Blood
    Pressure", "SpO2"), not abbreviations — plus an optional freeform extra
    field a nurse can add, which is never threshold-checked below."""
    __tablename__ = "admission_vitals"

    id = Column(Integer, primary_key=True, index=True)
    admission_id = Column(Integer, ForeignKey("admissions.id"), nullable=False)
    recorded_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    data = Column(Text, nullable=False)  # JSON: {"Blood Pressure": "120/80 mmHg", "SpO2": "98 %", ...}
    recorded_at = Column(DateTime, default=now_ist_naive)

    # Critical-value flagging — same shape as TestOrder's (Lab Flow Phase 1).
    is_critical = Column(Boolean, default=False, nullable=False)
    critical_note = Column(Text, nullable=True)          # human-readable breach description(s)
    critical_detected_at = Column(DateTime, nullable=True)
    critical_ack_at = Column(DateTime, nullable=True)        # when the admitting doctor acknowledged
    critical_escalated_at = Column(DateTime, nullable=True)  # set once escalated past the doctor