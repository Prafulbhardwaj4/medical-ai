from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime
from app.database import Base
from app.utils.timezone import now_ist_naive


class AdmissionWardType(Base):
    """Admin-configured ward/ICU/room categories used for IPD admissions —
    distinct from the OPD `rooms` table used for consultation room assignment."""
    __tablename__ = "admission_ward_types"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    name = Column(String, nullable=False)          # e.g. "General Ward", "ICU", "Private Room"
    total_beds = Column(Integer, nullable=False, default=0)
    daily_charge = Column(Float, nullable=False, default=0)
    created_at = Column(DateTime, default=now_ist_naive)