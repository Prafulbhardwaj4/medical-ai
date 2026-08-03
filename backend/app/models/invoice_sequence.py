from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from app.database import Base


class InvoiceSequence(Base):
    """Backs the atomic, race-safe number generator in app.utils.receipts —
    one row per (hospital, sequence type, financial year), row-locked via
    SELECT ... FOR UPDATE before incrementing (same pattern already used for
    slot-booking capacity in portal_appointments.py). Replaces the old
    count()+1 approach in next_receipt_number, which had a real race window
    between the count query and the insert under concurrent requests."""
    __tablename__ = "invoice_sequences"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    sequence_type = Column(String, nullable=False)  # "invoice" | "note_credit" | "note_debit"
    financial_year = Column(String, nullable=False)  # e.g. "2025-26" (April-March, Indian FY)
    last_number = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint('hospital_id', 'sequence_type', 'financial_year', name='uq_invoice_sequence'),
    )