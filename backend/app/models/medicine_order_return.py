from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class MedicineOrderReturn(Base):
    """OPD return — the patient paid the hospital pharmacy directly, so the
    money side is a real Refund (cash/card/upi/online), unlike IPD returns
    which just credit the running admission bill. Never restocks: disposition
    is always returned_to_supplier or sent_to_disposal — see AdmissionMedicationReturn
    for the same rule on the IPD side."""
    __tablename__ = "medicine_order_returns"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("medicine_orders.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    disposition = Column(String, nullable=False)  # "returned_to_supplier" | "sent_to_disposal"
    note = Column(Text, nullable=True)
    refund_id = Column(Integer, ForeignKey("refunds.id"), nullable=True)
    returned_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    returned_at = Column(DateTime, default=now_ist_naive, nullable=False)