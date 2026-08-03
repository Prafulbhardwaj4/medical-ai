from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive


class CreditDebitNote(Base):
    """GST-compliant supplementary document issued against an already-generated
    invoice — corrections never edit the original invoice directly. A credit
    note lowers the payable amount (overcharge, return, discount, refund); a
    debit note raises it (undercharge, missed line item). The original
    invoice's number/date are snapshotted here (invoice_number, invoice_date)
    so the note stays meaningful on its own even if the invoice relationship
    is ever unavailable."""
    __tablename__ = "credit_debit_notes"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    note_type = Column(String, nullable=False)  # "credit" | "debit"
    note_number = Column(String, unique=True, nullable=False, index=True)
    invoice_number = Column(String, nullable=True)  # snapshot of Invoice.receipt_number at note creation time
    invoice_date = Column(DateTime, nullable=True)  # snapshot of Invoice.generated_at
    amount = Column(Float, nullable=False)
    reason = Column(Text, nullable=False)
    refund_id = Column(Integer, ForeignKey("refunds.id"), nullable=True)  # set when raised via the refund flow
    created_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)  # null = system-generated (e.g. auto from a refund)
    created_at = Column(DateTime, default=now_ist_naive)