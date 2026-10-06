from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Float
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
    critical_low = Column(Float, nullable=True)   # hospital-configurable — below this value, a result is flagged critical (Phase 1)
    critical_high = Column(Float, nullable=True)  # above this value, a result is flagged critical (Phase 1)
    # Structured numeric reference ranges per sex (Phase 3 item 1) — derived from the free-text
    # reference_range_male/female on every save (listener below). Free text stays the display fallback.
    ref_low_male = Column(Float, nullable=True)
    ref_high_male = Column(Float, nullable=True)
    ref_low_female = Column(Float, nullable=True)
    ref_high_female = Column(Float, nullable=True)


from sqlalchemy import event as _event
from app.utils.ref_ranges import parse_range_bounds as _parse_bounds


def _derive_ref_bounds(mapper, connection, target):
    for sex in ("male", "female"):
        b = _parse_bounds(getattr(target, f"reference_range_{sex}", None))
        setattr(target, f"ref_low_{sex}", b[0] if b else None)
        setattr(target, f"ref_high_{sex}", b[1] if b else None)


_event.listen(TestCatalogParameter, "before_insert", _derive_ref_bounds)
_event.listen(TestCatalogParameter, "before_update", _derive_ref_bounds)