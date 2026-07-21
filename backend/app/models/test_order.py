from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from app.database import Base
from app.utils.timezone import now_ist_naive

class TestOrder(Base):
    __tablename__ = "test_orders"

    id = Column(Integer, primary_key=True, index=True)
    consultation_id = Column(Integer, ForeignKey("consultations.id"), nullable=True)
    admission_id = Column(Integer, ForeignKey("admissions.id"), nullable=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    test_id = Column(Integer, ForeignKey("test_catalog_items.id"), nullable=True)
    test_name = Column(String, nullable=False)
    price = Column(Float, nullable=False, default=0)
    included = Column(Boolean, default=True, nullable=False)
    status = Column(String, nullable=False, default="payment_pending")
    # payment_pending -> paid -> sample_collected -> processing -> completed

    paid_at = Column(DateTime, nullable=True)
    queued_at = Column(DateTime, nullable=True)  # set whenever this order enters a day's active queue (payment or requeue)
    collected_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    completed_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    result_data = Column(Text, nullable=True)  # JSON: {param_name: value}
    created_at = Column(DateTime, default=now_ist_naive)