from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime, ForeignKey
from datetime import datetime
from app.database import Base

class HospitalMedicine(Base):
    __tablename__ = "hospital_medicines"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    generic_name = Column(String, nullable=False)
    brand_names = Column(Text, nullable=True)
    category = Column(String, nullable=True)
    dosage_forms = Column(String, nullable=True)
    schedule = Column(String, nullable=False, default="otc")
    price = Column(Float, nullable=True)
    stock_quantity = Column(Integer, nullable=True, default=0)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)