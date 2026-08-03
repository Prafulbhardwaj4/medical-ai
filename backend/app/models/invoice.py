from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey
from app.database import Base
from app.utils.timezone import now_ist_naive

class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    checkin_id = Column(Integer, ForeignKey("checkins.id"), nullable=True, unique=True)
    admission_id = Column(Integer, ForeignKey("admissions.id"), nullable=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id"), nullable=False)
    items_json = Column(Text, nullable=False)  # [{type, name, qty, unit_price, line_total}]
    grand_total = Column(Float, nullable=False)  # tax-inclusive total actually payable
    subtotal = Column(Float, nullable=True)  # pre-tax amount; null on invoices generated before GST was wired in
    gst_total = Column(Float, nullable=True)
    generated_by = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    generated_from = Column(String, nullable=True)  # "reception" or "pharmacy"
    pdf_path = Column(String, nullable=True)
    payment_method = Column(String, nullable=True)  # "cash" | "card" | "upi"
    receipt_number = Column(String, unique=True, nullable=True, index=True)
    amount_collected = Column(Float, nullable=True)  # actual cash/card/upi taken at discharge (shortfall vs deposit) — distinct from grand_total, which is the full bill
    generated_at = Column(DateTime, default=now_ist_naive)
    place_of_supply = Column(String, nullable=True)  # GST-mandatory invoice field — state name, snapshotted from the hospital's own state at generation time (see app.utils.gst's documented intra-state assumption)

    # Reserved for e-invoicing (IRN/QR via the government IRP) — columns
    # only, nothing populates or reads these yet. Actual IRP integration is
    # a separate, deferred piece of work.
    irn = Column(String, nullable=True)  # Invoice Reference Number, returned by the IRP on successful registration
    irn_ack_no = Column(String, nullable=True)  # IRP acknowledgement number
    irn_ack_date = Column(DateTime, nullable=True)  # IRP acknowledgement timestamp
    einvoice_qr_data = Column(Text, nullable=True)  # signed QR payload string returned by the IRP
    einvoice_status = Column(String, nullable=True)  # "not_applicable" | "pending" | "generated" | "failed" — null today since nothing sets it yet
    place_of_supply = Column(String, nullable=True)  # snapshot of the hospital's state at generation time — see app.utils.gst's intra-state assumption