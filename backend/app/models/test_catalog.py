from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive

class TestCatalogItem(Base):
    __tablename__ = "test_catalog_items"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    name = Column(String, nullable=False)
    fee = Column(Float, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=now_ist_naive)
    category = Column(String, nullable=True)
    is_panel = Column(Boolean, default=False, nullable=False)
    purpose = Column(Text, nullable=True)
    reference_range_male = Column(String, nullable=True)
    reference_range_female = Column(String, nullable=True)
    unit = Column(String, nullable=True)
    turnaround_hours = Column(Integer, nullable=True)
    aliases = Column(Text, nullable=True)