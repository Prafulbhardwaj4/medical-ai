from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive

class TestCatalogParameter(Base):
    """A single sub-parameter of a panel test (e.g. Hemoglobin under CBC).
    Only used when the parent TestCatalogItem.is_panel is True — simple,
    single-value tests keep using the range/unit fields directly on
    TestCatalogItem, unchanged."""
    __tablename__ = "test_catalog_parameters"

    id = Column(Integer, primary_key=True, index=True)
    test_catalog_item_id = Column(Integer, ForeignKey("test_catalog_items.id"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    name = Column(String, nullable=False)
    unit = Column(String, nullable=True)
    reference_range_male = Column(String, nullable=True)
    reference_range_female = Column(String, nullable=True)
    purpose = Column(Text, nullable=True)
    display_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=now_ist_naive)