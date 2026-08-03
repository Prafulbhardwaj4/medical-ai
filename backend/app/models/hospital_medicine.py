from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive

class HospitalMedicine(Base):
    __tablename__ = "hospital_medicines"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    generic_name = Column(String, nullable=False)
    brand_names = Column(Text, nullable=True)
    brand_name = Column(String, nullable=True)  # set only on a brand-specific row (this row's own price/stock)
    parent_medicine_id = Column(Integer, ForeignKey("hospital_medicines.id"), nullable=True)  # links a brand row to its generic entry
    category = Column(String, nullable=True)
    dosage_forms = Column(String, nullable=True)
    strength = Column(String, nullable=True)  # e.g. "500mg" for tablets, "125mg/5ml" for syrups
    schedule = Column(String, nullable=False, default="otc")
    price = Column(Float, nullable=True)  # computed: price_per_pack / pack_size, kept for backward compat
    pack_size = Column(Integer, nullable=False, default=1)  # e.g. 10 tablets per strip; 1 for syrup/injection/etc
    price_per_pack = Column(Float, nullable=True)  # what admin actually enters — price printed on the box/strip
    billing_mode = Column(String, nullable=False, default="per_unit")  # "per_unit" or "per_pack"
    gst_percent = Column(Float, nullable=True)  # optional, applied on top of price at billing time — blank = no GST
    hsn_code = Column(String, nullable=True)  # this drug's own HSN code — varies per medicine, so it's set here rather than as a hospital-wide default like the other item types
    hsn_code = Column(String, nullable=True)  # HSN code for this medicine — pharmaceutical goods, distinct from the hospital's service SAC code
    nppa_ceiling_price = Column(Float, nullable=True)  # per-unit DPCO ceiling price, if this is an NLEM/DPCO-scheduled item — admin-entered, no live NPPA feed
    stock_quantity = Column(Integer, nullable=True, default=0)
    low_stock_threshold = Column(Integer, nullable=False, default=25)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=now_ist_naive)