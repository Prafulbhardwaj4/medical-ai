from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey
from sqlalchemy import event as _event
from app.database import Base
from app.utils.timezone import now_ist_naive
from app.utils.master_catalog import norm_name, clean_text


class MasterTest(Base):
    """Platform-wide test list kept by the Super Admin. No hospital_id and NO price.
    A hospital that selects a test gets its OWN copy (TestCatalogItem) with its own price.
    Never deleted, only deactivated. HIV and radiology tests never live here."""
    __tablename__ = "master_tests"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    name_norm = Column(String, nullable=False, unique=True, index=True)  # trimmed, lowercase, single spaces
    aliases = Column(Text, nullable=True)
    category = Column(String, nullable=True)
    required_tube = Column(String, nullable=True)
    fasting_required = Column(Boolean, default=False, nullable=False)
    turnaround_hours = Column(Integer, nullable=True)
    is_panel = Column(Boolean, default=False, nullable=False)
    purpose = Column(Text, nullable=True)
    # Single test only (blank for a panel). Ranges are TEXT so the hospital copy's listeners fill the numeric bounds.
    unit = Column(String, nullable=True)
    reference_range_male = Column(String, nullable=True)
    reference_range_female = Column(String, nullable=True)
    critical_low = Column(Float, nullable=True)
    critical_high = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=now_ist_naive)
    updated_at = Column(DateTime, default=now_ist_naive, onupdate=now_ist_naive)


class MasterTestParameter(Base):
    """One parameter row of a master panel (e.g. Haemoglobin under CBC)."""
    __tablename__ = "master_test_parameters"

    id = Column(Integer, primary_key=True, index=True)
    master_test_id = Column(Integer, ForeignKey("master_tests.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    unit = Column(String, nullable=True)
    reference_range_male = Column(String, nullable=True)
    reference_range_female = Column(String, nullable=True)
    purpose = Column(Text, nullable=True)
    critical_low = Column(Float, nullable=True)
    critical_high = Column(Float, nullable=True)
    display_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=now_ist_naive)


def _set_name_norm(mapper, connection, target):
    target.name = clean_text(target.name)
    target.name_norm = norm_name(target.name)


_event.listen(MasterTest, "before_insert", _set_name_norm)
_event.listen(MasterTest, "before_update", _set_name_norm)