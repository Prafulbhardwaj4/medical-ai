from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.consultation import Consultation

WINDOW_DAYS = 7


def is_order_expired(db: Session, patient_id: int, consultation_id: int, order_created_at: datetime) -> bool:
    """An order's window closes 7 calendar days after creation, OR at the
    patient's next consultation after the order was created — whichever
    happens first. Once expired, the order dies for good; no repayment,
    no requeue, no carryover.

    NOTE: TestOrder/MedicineOrder.created_at is still stored as naive UTC
    (datetime.utcnow() default) — this compares against datetime.utcnow(),
    not IST, to stay internally consistent with that column. This is a known
    piece of the broader #32/#33 IST audit; once created_at is migrated to
    IST-naive, this must switch to now_ist_naive() too."""
    if datetime.utcnow() - order_created_at > timedelta(days=WINDOW_DAYS):
        return True

    newer_consultation = db.query(Consultation).filter(
        Consultation.patient_id == patient_id,
        Consultation.id != consultation_id,
        Consultation.created_at > order_created_at
    ).first()
    return newer_consultation is not None