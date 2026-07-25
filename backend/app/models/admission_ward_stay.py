from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class AdmissionWardStay(Base):
    """One continuous segment of an admission spent in a single ward/bed at a
    single daily rate. A fresh row is opened every time reception processes a
    ward/bed change; the previous row's end_date is stamped at that moment.
    Billing sums each segment's own (days * daily_charge) instead of applying
    today's rate to the whole stay — so moving wards mid-stay doesn't
    retroactively re-bill already-completed days."""
    __tablename__ = "admission_ward_stays"

    id = Column(Integer, primary_key=True, index=True)
    admission_id = Column(Integer, ForeignKey("admissions.id"), nullable=False)
    ward_type_id = Column(Integer, ForeignKey("admission_ward_types.id"), nullable=True)
    ward_name = Column(String, nullable=False)   # snapshot — stays correct even if the ward type is later renamed/deleted
    bed_number = Column(String, nullable=False)
    daily_charge = Column(Float, nullable=False, default=0)

    start_date = Column(DateTime, default=now_ist_naive, nullable=False)
    end_date = Column(DateTime, nullable=True)    # null = this is the current/ongoing segment

    changed_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)  # who made the move (reception/admin)
    created_at = Column(DateTime, default=now_ist_naive)