from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive

class AiScribeTopup(Base):
    """A purchased block of extra AI Scribe consultations (item 3). Tracked
    as its own row — not just added to the tier cap — because each block has
    its own 30-day expiry and its own price, independent of the billing
    cycle and independent of whatever tier the hospital is on. Consumption
    is tracked per-topup (consultations_used) so remaining balance across
    multiple active top-ups can always be computed exactly."""
    __tablename__ = "ai_scribe_topups"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)

    block_size = Column(Integer, nullable=False)  # 250 | 350 | 500 (item 3) — kept alongside consultations_granted in case a custom block is ever sold
    consultations_granted = Column(Integer, nullable=False)
    consultations_used = Column(Integer, default=0, nullable=False)

    price_paid = Column(Float, nullable=False)
    payment_collected = Column(Boolean, nullable=False, default=False)  # confirmed at purchase time via the super-admin popup (item 3) — never created as True by anything else

    purchased_at = Column(DateTime, default=now_ist_naive)
    expires_at = Column(DateTime, nullable=False)  # purchased_at + 30 days, fixed at creation — does not move with the billing cycle
    purchased_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)  # super admin who bought it