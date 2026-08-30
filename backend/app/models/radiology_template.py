from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive

class RadiologyTemplate(Base):
    """A study type the hospital offers (e.g. 'USG Abdomen', 'X-Ray Chest PA', 'CT Brain').
    Parallels TestCatalogItem, but represents an imaging study rather than a lab
    test — no reference-range/unit fields, since findings are narrative per
    section, not numeric (see Part 1 item 1)."""
    __tablename__ = "radiology_templates"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    name = Column(String, nullable=False)  # e.g. "USG Abdomen"
    study_type = Column(String, nullable=False)  # "xray" | "ct" | "mri" | "ultrasound"
    fee = Column(Float, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=now_ist_naive)