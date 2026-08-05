from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class PatientAllergy(Base):
    """A patient-level allergy — persists across visits/admissions, since an
    allergy discovered during one admission has to be visible on every
    future visit too, not just this stay. Never hard-deleted: a mistaken
    entry is retracted (is_active=False) so the correction itself stays
    on record."""
    __tablename__ = "patient_allergies"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    allergen = Column(String, nullable=False)
    reaction = Column(Text, nullable=True)
    severity = Column(String, nullable=False, default="moderate")  # mild / moderate / severe
    is_active = Column(Boolean, default=True, nullable=False)
    noted_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    noted_at = Column(DateTime, default=now_ist_naive)