from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from app.database import Base
from app.utils.timezone import now_ist_naive

class RadiologyOrder(Base):
    """Parallels TestOrder, but deliberately simpler: no sample-collection
    stage, no accession numbering, no NABL/critical-value logic — imaging has
    no physical sample and findings are narrative text, not values with
    ranges (Part 1 item 1)."""
    __tablename__ = "radiology_orders"

    id = Column(Integer, primary_key=True, index=True)
    consultation_id = Column(Integer, ForeignKey("consultations.id"), nullable=True)
    admission_id = Column(Integer, ForeignKey("admissions.id"), nullable=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    template_id = Column(Integer, ForeignKey("radiology_templates.id"), nullable=True)  # nullable: a later-deactivated template shouldn't orphan past orders
    study_name = Column(String, nullable=False)  # denormalized at order time, mirrors TestOrder.test_name
    study_type = Column(String, nullable=False)  # "xray" | "ct" | "mri" | "ultrasound" — denormalized for display/filtering without a join
    price = Column(Float, nullable=False, default=0)

    order_batch_id = Column(String, nullable=True, index=True)  # orders placed together in one "Order Imaging" action share a batch id — same convention as TestOrder.order_batch_id
    included = Column(Boolean, default=True, nullable=False)

    status = Column(String, nullable=False, default="payment_pending")
    # payment_pending -> paid -> reported -> verified_released
    # (no sample_collected/processing stages — nothing physical is collected for imaging)

    priority = Column(String, nullable=False, default="routine")  # "routine" | "urgent" | "stat"
    clinical_indication = Column(Text, nullable=True)  # indication for the scan — also reused by PCPNDT Form F (item 7)
    is_reproductive_age_woman = Column(Boolean, default=False, nullable=False)  # the Form F trigger checkbox (item 7) — only meaningful when study_type == "ultrasound"

    paid_at = Column(DateTime, nullable=True)
    payment_method = Column(String, nullable=True)  # "cash" | "card" | "upi"
    queued_at = Column(DateTime, nullable=True)

    sections_data = Column(Text, nullable=True)  # JSON: {section_name: finding_text} — seeded from template defaults, radiologist edits only what's abnormal (item 5)
    impression = Column(Text, nullable=True)  # always free-text, never templated (item 2)
    advised = Column(Text, nullable=True)     # always free-text, never templated (item 2)

    reported_at = Column(DateTime, nullable=True)
    reported_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)

    verified_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    self_verified_sole_staff = Column(Boolean, default=False, nullable=False)  # same integrity-tracking pattern as TestOrder.self_verified_sole_staff
    verified_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=now_ist_naive)