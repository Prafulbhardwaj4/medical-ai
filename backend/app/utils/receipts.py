from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError


def _financial_year_label(dt) -> str:
    """Indian FY: April-March. A date anywhere from Apr <year> through
    Mar <year+1> belongs to FY "<year>-<year+1's last 2 digits>"."""
    year = dt.year if dt.month >= 4 else dt.year - 1
    return f"{year}-{str(year + 1)[-2:]}"


def _next_sequence_number(db: Session, hospital_id: int, sequence_type: str, fy: str) -> int:
    """Atomic, race-safe, per-hospital, per-financial-year counter. Row-level
    locked via SELECT ... FOR UPDATE (same pattern already used for
    slot-booking capacity in portal_appointments.py) so two concurrent
    requests can never walk away with the same number."""
    from app.models.invoice_sequence import InvoiceSequence

    seq = db.query(InvoiceSequence).filter(
        InvoiceSequence.hospital_id == hospital_id,
        InvoiceSequence.sequence_type == sequence_type,
        InvoiceSequence.financial_year == fy
    ).with_for_update().first()

    if not seq:
        # First number of this hospital/type/FY combo — create the counter
        # row now. If another concurrent request is creating the exact same
        # row, the unique constraint blocks/rejects the second insert; on
        # that race we roll back and re-read, which will now see (and lock)
        # the row the other request created.
        seq = InvoiceSequence(hospital_id=hospital_id, sequence_type=sequence_type, financial_year=fy, last_number=0)
        db.add(seq)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            seq = db.query(InvoiceSequence).filter(
                InvoiceSequence.hospital_id == hospital_id,
                InvoiceSequence.sequence_type == sequence_type,
                InvoiceSequence.financial_year == fy
            ).with_for_update().first()

    seq.last_number += 1
    db.flush()
    return seq.last_number


def next_receipt_number(db: Session, hospital) -> str:
    """Sequential, unique per financial year, per hospital's own GSTIN.
    Format: <hospital_code>-<FY>-00001, e.g. GEN-2025-26-00001. Atomic under
    concurrent requests — see _next_sequence_number."""
    from app.utils.timezone import now_ist_naive
    fy = _financial_year_label(now_ist_naive())
    n = _next_sequence_number(db, hospital.id, "invoice", fy)
    return f"{hospital.hospital_code}-{fy}-{n:05d}"


def next_note_number(db: Session, hospital, note_type: str) -> str:
    """Sequential, unique per financial year, per hospital, per note type.
    Format: <hospital_code>-CN-<FY>-00001 / <hospital_code>-DN-<FY>-00001.
    Same atomic sequence mechanism as next_receipt_number."""
    from app.utils.timezone import now_ist_naive
    fy = _financial_year_label(now_ist_naive())
    prefix = "CN" if note_type == "credit" else "DN"
    n = _next_sequence_number(db, hospital.id, f"note_{note_type}", fy)
    return f"{hospital.hospital_code}-{prefix}-{fy}-{n:05d}"


def generate_verify_hash(record_id, hospital_id: int, kind: str = "invoice") -> str:
    """Deterministic-but-unguessable verification code for the QR /
    verify.html flow — same SECRET_KEY-salted sha256-truncation pattern
    used across invoices, lab reports, and radiology reports. `kind`
    namespaces the hash so an invoice id and a test_order id sharing the
    same integer never collide. Default kind="invoice" keeps every
    existing invoice.verify_hash value byte-identical to before — this
    is a generalization, not a behavior change for invoices."""
    import hashlib
    from app.config import settings
    hash_input = f"{kind}-{record_id}-{hospital_id}-{settings.SECRET_KEY}"
    return hashlib.sha256(hash_input.encode()).hexdigest()[:16].upper()


def next_report_number(db: Session, hospital, report_type: str) -> str:
    """Sequential, unique per financial year, per hospital, per report type
    ("lab" | "radiology") — same atomic mechanism as next_receipt_number.
    Format: <hospital_code>-LAB-<FY>-00001 / <hospital_code>-RAD-<FY>-00001
    (item 3 — extends the existing numbering pattern, doesn't invent a new one)."""
    from app.utils.timezone import now_ist_naive
    fy = _financial_year_label(now_ist_naive())
    prefix = "LAB" if report_type == "lab" else "RAD"
    n = _next_sequence_number(db, hospital.id, f"report_{report_type}", fy)
    return f"{hospital.hospital_code}-{prefix}-{fy}-{n:05d}"