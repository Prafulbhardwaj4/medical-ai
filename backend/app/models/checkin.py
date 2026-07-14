from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, Text, Float, Boolean
from app.database import Base
from app.utils.timezone import now_ist_naive

class Checkin(Base):
    __tablename__ = "checkins"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    token_number = Column(String, unique=True, nullable=False, index=True)
    issue_category = Column(String, nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    visit_date = Column(Date, nullable=False, index=True)
    created_at = Column(DateTime, default=now_ist_naive)

    nurse_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    vitals_status = Column(String, default="none", nullable=False)
    vitals_data = Column(Text, nullable=True)
    vitals_recorded_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    vitals_recorded_at = Column(DateTime, nullable=True)

    post_consult_status = Column(String, default="none", nullable=False)
    post_consult_note = Column(Text, nullable=True)
    post_consult_data = Column(Text, nullable=True)
    post_consult_recorded_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    post_consult_recorded_at = Column(DateTime, nullable=True)

    consultation_fee = Column(Float, nullable=True)
    test_fee = Column(Float, nullable=True)
    is_paid = Column(Boolean, default=False, nullable=False)
    paid_at = Column(DateTime, nullable=True)

    is_finalized = Column(Boolean, default=False, nullable=False)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)