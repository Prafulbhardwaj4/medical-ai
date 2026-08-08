from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime
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
    default_deposit = Column(Float, nullable=False, default=0)  # pre-filled at admission, reception can override
    is_icu = Column(Boolean, nullable=False, default=False)  # ICU/CCU/ICCU/NICU — always GST-exempt regardless of daily rate
    is_ot = Column(Boolean, nullable=False, default=False)  # Operation Theatre segment — moving an admission into this ward type auto-bills ot_charge (see change_ward)
    ot_charge = Column(Float, nullable=True)  # flat per-use OT fee, billed once on entry into an is_ot ward type — not a daily rate like daily_charge
    category = Column(String, nullable=False, default="general")  # "general" | "icu" | "private" | "maternity" | "nicu" | "isolation" | "day_care" | "other" — structural label, seeded as presets on new hospital setup; admin can rename/add/remove freely
    is_emergency_ward = Column(Boolean, nullable=False, default=False)  # exactly one ward type per hospital can be flagged as this — setting it clears the flag from any other ward type at the same hospital (see update_ward_type/create_ward_type)
    created_at = Column(DateTime, default=now_ist_naive)