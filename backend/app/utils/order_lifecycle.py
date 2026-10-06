from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.consultation import Consultation
from app.models.medicine_order import MedicineOrder
from app.utils.timezone import now_ist_naive

WINDOW_DAYS = 7


def is_order_expired(db: Session, patient_id: int, consultation_id: int, order_created_at: datetime) -> bool:
    """An order's window closes 7 calendar days after creation, OR at the
    patient's next consultation after the order was created — whichever
    happens first. Once expired, the order dies for good; no repayment,
    no requeue, no carryover."""
    if now_ist_naive() - order_created_at > timedelta(days=WINDOW_DAYS):
        return True

    if consultation_id is None:
        return False  # walk-in / self-referred order: only the 7-day rule applies

    newer_consultation = db.query(Consultation).filter(
        Consultation.patient_id == patient_id,
        Consultation.id != consultation_id,
        Consultation.created_at > order_created_at
    ).first()
    return newer_consultation is not None



def refresh_consultation_dispensed(db: Session, consultation: Consultation) -> None:
    """Consultation.is_dispensed is DERIVED from its orders, not a one-way switch: it is
    True only when something was dispensed AND no included order is still waiting
    (advised/unpaid or paid-not-handed-over). A patient who collects some medicines now
    and the rest later therefore stays 'pending' until the rest is dealt with.
    Caller commits."""
    orders = db.query(MedicineOrder).filter(MedicineOrder.consultation_id == consultation.id).all()
    waiting = any(o.included and o.status in ("advised", "paid") for o in orders)
    any_dispensed = any(o.status == "dispensed" for o in orders)
    if any_dispensed and not waiting:
        consultation.is_dispensed = True
        if consultation.dispensed_at is None:
            consultation.dispensed_at = now_ist_naive()
    else:
        consultation.is_dispensed = False