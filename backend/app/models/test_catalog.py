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
    critical_low = Column(Float, nullable=True)   # hospital-configurable — below this value, a result is flagged critical (Phase 1)
    critical_high = Column(Float, nullable=True)  # above this value, a result is flagged critical (Phase 1)
    fasting_required = Column(Boolean, default=False, nullable=False)  # e.g. lipid profile, fasting glucose — surfaced to collector at draw time (Phase 3 item 8)
    required_tube = Column(String, nullable=True)  # e.g. "EDTA (purple top)", "Fluoride (grey top)" — surfaced at collection (Phase 4 item 11)
    is_irreplaceable_sample = Column(Boolean, default=False, nullable=False)  # CSF, biopsy tissue, bone marrow, etc. — never hard-rejected, gets a report caveat instead (Phase 4 item 14)
    is_nabl_accredited = Column(Boolean, default=False, nullable=False)  # hospital-configurable per test — controls whether the report shows the accreditation statement or plainly says it's out of scope (Phase 5 item 19)
    is_hiv_test = Column(Boolean, default=False, nullable=False)  # routed through the distinct, restricted HIV release path instead of the generic queue (Phase 6 item 21)
    notifiable_disease_id = Column(Integer, ForeignKey("notifiable_diseases.id"), nullable=True)
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


_event.listen(TestCatalogItem, "before_insert", _derive_ref_bounds)
_event.listen(TestCatalogItem, "before_update", _derive_ref_bounds)  # links this test to a hospital-configured IDSP disease (Phase 6 item 23)