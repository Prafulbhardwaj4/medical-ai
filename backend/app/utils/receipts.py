from sqlalchemy.orm import Session


def next_receipt_number(db: Session, hospital) -> str:
    """Sequential, human-readable receipt number scoped per hospital.
    Format: <hospital_code>-00001. Computed from existing invoice count —
    fine at real single-hospital invoice volumes; each hospital's count
    query only touches its own rows."""
    from app.models.invoice import Invoice
    count = db.query(Invoice).filter(Invoice.hospital_id == hospital.id).count()
    return f"{hospital.hospital_code}-{count + 1:05d}"