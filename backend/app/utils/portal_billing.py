from sqlalchemy.orm import Session

from app.models.doctor import Doctor


def current_doctor_fee(db: Session, doctor_id: int) -> float:
    """Doctor's own consultation fee, falling back to the hospital default.
    Used to snapshot what a portal appointment actually costs at the moment
    payment (or a hospital-suggested change) happens, so later fee changes
    don't retroactively affect an already-priced booking."""
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        return 0.0
    return doctor.consultation_fee or doctor.default_consultation_fee or 0.0


def create_patient_cancellation_refund(db: Session, appt, reason: str, percent: float = None, fixed_amount: float = None) -> None:
    """Reuses the existing Refund model/mechanism reception already uses for
    walk-in refunds. patient_id and processed_by are left null: no staff
    actor processed this (patient self-cancelled, or the system
    auto-declined), and a genuinely new patient may not have a Patient row
    yet at all."""
    from app.models.refund import Refund

    base = appt.fee_amount or 0
    if fixed_amount is not None:
        amount = fixed_amount
    elif percent is not None:
        amount = round(base * percent / 100, 2)
    else:
        return
    if not amount or amount <= 0:
        return

    patient_id = None
    if appt.profile_link_id and appt.profile_link and appt.profile_link.patient:
        patient_id = appt.profile_link.patient.id

    db.add(Refund(
        patient_id=patient_id, hospital_id=appt.hospital_id,
        source_type="appointment", source_id=appt.id, amount=amount,
        channel="online", status="pending", reason=reason,
        processed_by=None,
    ))