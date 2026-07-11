from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey, DateTime, UniqueConstraint
from datetime import datetime
from app.database import Base

class MedicineBatch(Base):
    __tablename__ = "medicine_batches"
    __table_args__ = (UniqueConstraint('medicine_id', 'batch_number', name='uq_medicine_batch'),)

    id = Column(Integer, primary_key=True, index=True)
    medicine_id = Column(Integer, ForeignKey("hospital_medicines.id"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    batch_number = Column(String, nullable=True, index=True)
    quantity = Column(Integer, nullable=False)
    expiry_date = Column(Date, nullable=True)
    received_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)