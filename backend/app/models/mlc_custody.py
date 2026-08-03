from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class MlcChainOfCustody(Base):
    """Append-only chain-of-custody log for MLC-flagged samples. There is
    deliberately no update/delete endpoint anywhere for this table — every
    handoff is a new row, never edited, so the log itself can stand up as
    evidence of an unbroken chain (Phase 6 item 22)."""
    __tablename__ = "mlc_chain_of_custody"

    id = Column(Integer, primary_key=True, index=True)
    test_order_id = Column(Integer, ForeignKey("test_orders.id"), nullable=False, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)

    stage = Column(String, nullable=False)
    # "collected_from_patient" | "handed_to_transport" | "received_at_lab" |
    # "moved_to_storage" | "processing_started" | "released_to_authority" |
    # "rejected" | "other"

    handed_over_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    handed_over_by_external_name = Column(String, nullable=True)  # e.g. a police officer, courier — no system account
    received_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    received_by_external_name = Column(String, nullable=True)

    seal_intact = Column(Boolean, nullable=True)
    seal_number = Column(String, nullable=True)
    notes = Column(Text, nullable=True)

    recorded_by = Column(Integer, ForeignKey("doctors.id"), nullable=False)  # who is logging this entry right now
    recorded_at = Column(DateTime, default=now_ist_naive, nullable=False)