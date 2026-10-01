from sqlalchemy import Column, Integer, String, ForeignKey
from app.database import Base


class MedicineOrderBatch(Base):
    """Which batch(es) a dispensed OPD order was actually taken from (batch traceability
    for recalls and the Schedule H1/X registers). One order can span several batches.
    batch_id is NULL for units taken from legacy stock that has no batch record."""
    __tablename__ = "medicine_order_batches"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("medicine_orders.id"), nullable=False, index=True)
    batch_id = Column(Integer, ForeignKey("medicine_batches.id"), nullable=True)
    batch_number = Column(String, nullable=True)  # copied at dispense time, survives later batch edits/removal
    quantity = Column(Integer, nullable=False)