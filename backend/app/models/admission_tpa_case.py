from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class AdmissionTpaCase(Base):
    """TPA/insurance cashless paper-trail for an admission — MedScribe doesn't
    talk to the insurer, it just holds the record while hospital staff work
    the case through email/TPA-portal outside the software (Admission-IPD Flow §5)."""
    __tablename__ = "admission_tpa_cases"

    id = Column(Integer, primary_key=True, index=True)
    admission_id = Column(Integer, ForeignKey("admissions.id"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)

    insurer_name = Column(String, nullable=False)
    policy_number = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")  # pending | query_raised | approved | denied
    authorized_amount = Column(Float, nullable=True)
    room_category_eligibility = Column(String, nullable=True)  # free-text policy description, e.g. "up to twin-sharing"
    eligible_daily_rate = Column(Float, nullable=True)  # numeric room-rent eligibility (₹/day) — used to compute the proportionate deduction estimate; the free-text field above stays as the human-readable policy note
    copay_notes = Column(Text, nullable=True)
    query_notes = Column(Text, nullable=True)  # what the TPA is asking for, when status = query_raised

    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    created_at = Column(DateTime, default=now_ist_naive)
    updated_at = Column(DateTime, default=now_ist_naive, onupdate=now_ist_naive)
    resolved_at = Column(DateTime, nullable=True)  # set when status becomes approved/denied

    # Settlement phase — distinct from the pre-auth phase above. Only
    # meaningful once status="approved". Tracked independently of
    # Admission.status, since real settlement can lag actual physical
    # discharge by weeks.
    settlement_status = Column(String, nullable=True)  # null (no claim submitted yet) | "awaiting_settlement" | "settled"
    claim_submitted_amount = Column(Float, nullable=True)  # the TPA-covered amount actually applied at discharge (or submitted manually)
    claim_submitted_at = Column(DateTime, nullable=True)
    settled_amount = Column(Float, nullable=True)  # what the TPA actually paid — logged manually once received, since MedScribe doesn't integrate with insurers
    settled_at = Column(DateTime, nullable=True)
    settlement_notes = Column(Text, nullable=True)