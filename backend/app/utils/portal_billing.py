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


def is_fee_difference_reason(reason) -> bool:
    """A refund of the fee difference after a move to a cheaper doctor. The fee on the appointment is already lowered
    by that amount, so it is not counted against what is left to refund."""
    text = (reason or "").lower()
    return "lower-fee" in text or "lower fee" in text


def appointment_refund_room(db: Session, appt) -> float:
    """What can still be refunded for this appointment: what the patient really paid, minus refunds already created
    (pending or paid out; closed-without-paying ones do not count)."""
    from app.models.refund import Refund
    from app.services.reception_appointments import paid_amount
    already = 0.0
    for amount, why in db.query(Refund.amount, Refund.reason).filter(
        Refund.source_type == "appointment", Refund.source_id == appt.id, Refund.status != "dismissed"
    ).all():
        if not is_fee_difference_reason(why):
            already += float(amount or 0)
    return max(round(paid_amount(db, appt) - already, 2), 0.0)


def create_patient_cancellation_refund(db: Session, appt, reason: str, percent: float = None, fixed_amount: float = None) -> None:
    """Reuses the existing Refund model/mechanism reception already uses for
    walk-in refunds. patient_id and processed_by are left null: no staff
    actor processed this (patient self-cancelled, or the system
    auto-declined), and a genuinely new patient may not have a Patient row
    yet at all."""
    from app.models.refund import Refund

    # Never refund money that was never collected.
    if getattr(appt, "payment_status", None) != "paid":
        return

    # One refund per appointment per reason: guards against double-click / double sweep.
    if db.query(Refund).filter(
        Refund.source_type == "appointment", Refund.source_id == appt.id, Refund.reason == reason
    ).first():
        return

    base = appt.fee_amount or 0
    if fixed_amount is not None:
        amount = fixed_amount
    elif percent is not None:
        # Never more than what is still left to refund for this appointment.
        amount = min(round(base * percent / 100, 2), appointment_refund_room(db, appt))
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