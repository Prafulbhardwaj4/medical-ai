from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from sqlalchemy import event as _event
from app.database import Base
from app.utils.timezone import now_ist_naive
from app.utils.master_catalog import norm_name, clean_text, medicine_display_name


class MasterMedicine(Base):
    """Platform-wide generic medicine list kept by the Super Admin. No hospital_id, NO price,
    NO brand, NO stock. A hospital that selects one gets its OWN generic (parent) row.
    Never deleted, only deactivated."""
    __tablename__ = "master_medicines"

    id = Column(Integer, primary_key=True, index=True)
    generic_name = Column(String, nullable=False)
    strength = Column(String, nullable=True)
    dosage_form = Column(String, nullable=True)           # same list as the Dosage Form dropdown
    schedule = Column(String, nullable=False, default="otc")  # "otc" / "h" / "h1" / "x"
    default_pack_size = Column(Integer, nullable=False, default=1)
    default_billing_mode = Column(String, nullable=False, default="per_unit")  # "per_unit" / "per_pack"
    gst_percent = Column(Float, nullable=True)
    hsn_code = Column(String, nullable=True)
    category = Column(String, nullable=True)
    display_name = Column(String, nullable=False)          # "generic strength form" (derived on every save)
    name_norm = Column(String, nullable=False, unique=True, index=True)  # normalized display_name
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=now_ist_naive)
    updated_at = Column(DateTime, default=now_ist_naive, onupdate=now_ist_naive)


def _set_display_and_norm(mapper, connection, target):
    target.generic_name = clean_text(target.generic_name)
    target.strength = clean_text(target.strength)
    target.dosage_form = clean_text(target.dosage_form)
    target.display_name = medicine_display_name(target.generic_name, target.strength, target.dosage_form)
    target.name_norm = norm_name(target.display_name)


_event.listen(MasterMedicine, "before_insert", _set_display_and_norm)
_event.listen(MasterMedicine, "before_update", _set_display_and_norm)