from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive

class MedicineOrder(Base):
    __tablename__ = "medicine_orders"

    id = Column(Integer, primary_key=True, index=True)
    consultation_id = Column(Integer, ForeignKey("consultations.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    catalog_medicine_id = Column(Integer, ForeignKey("hospital_medicines.id"), nullable=True)
    medicine_name = Column(String, nullable=False)
    brand_name = Column(String, nullable=True)
    dosage = Column(String, nullable=True)
    frequency = Column(String, nullable=True)
    duration = Column(String, nullable=True)
    unit_price = Column(Float, nullable=True)
    quantity = Column(Integer, nullable=True)
    included = Column(Boolean, default=True, nullable=False)
    status = Column(String, nullable=False, default="advised")  # advised -> paid -> dispensed (or unavailable = advised outside, never billed)
    paid_at = Column(DateTime, nullable=True)
    queued_at = Column(DateTime, nullable=True)  # set whenever this order enters a day's active queue (payment or requeue)
    dispensed_at = Column(DateTime, nullable=True)
    billed_quantity = Column(Integer, nullable=True)  # actually charged/dispensed qty, capped by stock at payment time
    substitute_for_id = Column(Integer, ForeignKey("medicine_orders.id"), nullable=True)
    created_at = Column(DateTime, default=now_ist_naive)