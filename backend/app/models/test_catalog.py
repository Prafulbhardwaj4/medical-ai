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
    notifiable_disease_id = Column(Integer, ForeignKey("notifiable_diseases.id"), nullable=True)  # links this test to a hospital-configured IDSP disease (Phase 6 item 23)