"""Reception-side helpers for cancelling and rescheduling an appointment, and for resending the token message.

Everything here runs inside the CALLER's transaction: nothing is committed in this file, so the change, its refund,
its messages and its audit entry are saved (or rolled back) together by the router."""
import re
from datetime import timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.checkin import Checkin
from app.models.opd_charge import OpdCharge
from app.models.portal import Appointment, AppointmentStatus
from app.models.refund import Refund
from app.models.whatsapp_message import WhatsappMessage
from app.services import whatsapp_messages as wa
from app.services import whatsapp_appointments as wa_appt
from app.utils.timezone import now_ist_naive

ACTIONABLE_STATUSES = (AppointmentStatus.booked, AppointmentStatus.pending_review, AppointmentStatus.confirmed)
SETTLE_CHANNELS = ("cash", "card", "upi")
DIFF_CHARGE_PREFIX = "Reschedule fee difference"
CANCEL_REFUND_PREFIX = "Cancelled by reception"

CANCEL_REASONS = {
    "patient_asked": "Patient asked",
    "doctor_unavailable": "Doctor unavailable",
    "hospital_reason": "Hospital reason",
    "other": "Other",
}


def reason_label(value: Optional[str]) -> str:
    key = (value or "").strip()
    if key in CANCEL_REASONS:
        return CANCEL_REASONS[key]
    for label in CANCEL_REASONS.values():
        if key.lower() == label.lower():
            return label
    raise HTTPException(status_code=400, detail="Please choose a reason for the cancellation")


def clean_note(value: Optional[str], max_len: int = 200) -> str:
    """Untrusted free text: control characters removed, single spaces, length limited."""
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", value or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def lock_appointment(db: Session, appointment_id: int, hospital_id: int) -> Appointment:
    """The appointment row is locked for the rest of the transaction, and only the user's own hospital is searched,
    so changing the id in a request finds nothing."""
    appt = db.query(Appointment).filter(
        Appointment.id == appointment_id, Appointment.hospital_id == hospital_id
    ).with_for_update().first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appt


def refuse_if_changed(appt: Appointment, expected_requested_time: Optional[str]) -> None:
    """Two people on the same row, or a double click on a stale screen: the screen sends the time it was showing."""
    if not expected_requested_time:
        return
    if appt.requested_time.isoformat() != str(expected_requested_time).strip():
        raise HTTPException(status_code=409, detail="This appointment was just changed by someone else. Please refresh the list and try again.")


def visit_for(db: Session, appt: Appointment):
    return db.query(Checkin).filter(Checkin.portal_appointment_id == appt.id).first()


def block_reason(db: Session, appt: Appointment) -> Optional[str]:
    """Plain-words reason why reception can no longer cancel / reschedule this appointment, or None."""
    if appt.status == AppointmentStatus.cancelled:
        return "This appointment is already cancelled."
    if appt.status == AppointmentStatus.completed:
        return "This appointment is already completed."
    if appt.status not in ACTIONABLE_STATUSES:
        return "This appointment can no longer be changed."
    visit = visit_for(db, appt)
    if visit is not None:
        if visit.invoice_id or visit.is_finalized:
            return "This visit is already billed, so the appointment cannot be changed."
        from app.models.consultation import Consultation
        if visit.token_number and db.query(Consultation.id).filter(Consultation.token_number == visit.token_number).first():
            return "The doctor has already seen this patient, so the appointment cannot be changed."
    return None


def require_actionable(db: Session, appt: Appointment) -> None:
    why = block_reason(db, appt)
    if why:
        raise HTTPException(status_code=400, detail=why)


def unpaid_difference_charges(db: Session, appt: Appointment) -> list:
    """A fee difference that was already moved onto the visit bill but has not been collected yet."""
    visit = visit_for(db, appt)
    if visit is None:
        return []
    return db.query(OpdCharge).filter(
        OpdCharge.checkin_id == visit.id,
        OpdCharge.description.like(DIFF_CHARGE_PREFIX + "%"),
        OpdCharge.status != "paid",
    ).all()


def paid_amount(db: Session, appt: Appointment) -> float:
    """What the patient really paid for this appointment (never more). The fee on the row may already include a
    higher-fee difference that is still only owed, so that part is taken out."""
    if appt.payment_status != "paid":
        return 0.0
    total = float(appt.fee_amount or 0) - float(appt.reschedule_balance_due or 0)
    for charge in unpaid_difference_charges(db, appt):
        total -= float(charge.amount or 0) * int(charge.quantity or 1)
    return max(round(total, 2), 0.0)


def default_channel(appt: Appointment) -> str:
    """Refunds go back the way the money came in (cash, card or UPI); anything else defaults to cash."""
    method = (appt.payment_method or "").strip().lower()
    return method if method in SETTLE_CHANNELS else "cash"


def patient_for(appt: Appointment):
    if appt.profile_link_id and appt.profile_link and appt.profile_link.patient:
        return appt.profile_link.patient
    return None


def patient_name(appt: Appointment) -> str:
    patient = patient_for(appt)
    return patient.name if patient else (appt.new_patient_name or "Portal patient")


def add_refund(db: Session, appt: Appointment, amount: float, reason: str, staff, cap: float) -> Optional[Refund]:
    """A pending refund (reception pays it out from the Refunds page). Never above `cap`, never for money that was
    not collected, and never a second time for the same reason."""
    amount = round(float(amount or 0), 2)
    if appt.payment_status != "paid" or amount <= 0 or cap <= 0:
        return None
    if amount > cap + 0.001:
        raise HTTPException(status_code=400, detail="The refund cannot be more than what the patient paid.")
    from app.utils.portal_billing import appointment_refund_room, is_fee_difference_reason
    if not is_fee_difference_reason(reason) and amount > appointment_refund_room(db, appt) + 0.001:
        raise HTTPException(status_code=400, detail="This appointment has already been refunded. It cannot be refunded twice.")
    if db.query(Refund.id).filter(
        Refund.source_type == "appointment", Refund.source_id == appt.id, Refund.reason == reason,
        Refund.status != "dismissed",
    ).first():
        raise HTTPException(status_code=400, detail="A refund for this appointment was already created.")
    patient = patient_for(appt)
    refund = Refund(
        patient_id=patient.id if patient else None, hospital_id=appt.hospital_id,
        source_type="appointment", source_id=appt.id, amount=amount,
        channel=default_channel(appt), status="pending", reason=reason, processed_by=staff.id,
    )
    db.add(refund)
    db.flush()
    return refund


def release_slot(db: Session, slot_id: Optional[int]) -> None:
    """Gives one place back in a slot. A single UPDATE, so it is safe even when two people act at once."""
    if not slot_id:
        return
    from app.models.doctor_slot import DoctorSlot
    db.query(DoctorSlot).filter(DoctorSlot.id == slot_id, DoctorSlot.booked_count > 0).update(
        {DoctorSlot.booked_count: DoctorSlot.booked_count - 1}, synchronize_session=False)


def take_slot_place(db: Session, slot) -> None:
    """Takes one place in a slot only if it is still free (one UPDATE with the capacity test inside it), so two
    receptionists clicking at the same moment can never double book the last place."""
    from app.models.doctor_slot import DoctorSlot
    taken = db.query(DoctorSlot).filter(
        DoctorSlot.id == slot.id, DoctorSlot.booked_count < DoctorSlot.capacity
    ).update({DoctorSlot.booked_count: DoctorSlot.booked_count + 1}, synchronize_session=False)
    if taken != 1:
        raise HTTPException(status_code=400, detail="That time slot is full. Please pick another.")
    db.refresh(slot)


# ---------------------------------------------------------------------------
# Resend token number
# ---------------------------------------------------------------------------
def resend_token_message(db: Session, appt: Appointment, staff) -> dict:
    """Creates the visit/token message again with the SAME token number (generating the token first if the visit has
    none yet, exactly as the arrival flow does). Does not mark the patient as arrived and takes no payment."""
    if appt.status not in (AppointmentStatus.booked, AppointmentStatus.confirmed, AppointmentStatus.pending_review):
        raise HTTPException(status_code=400, detail="A token cannot be sent for this appointment.")
    hospital, doctor, account, patient, name = wa_appt._context(db, appt)
    if account is None or not (account.phone or "").strip():
        raise HTTPException(status_code=400, detail="There is no mobile number on this booking, so the token cannot be sent.")

    now = now_ist_naive()
    existed = visit_for(db, appt) is not None or bool(wa_appt.reserved_token_for_appointment(db, appt.id))
    token, checkin = wa_appt._token_for(db, appt, hospital)

    # A double click (or two receptionists) within a minute: one message only.
    recent = db.query(WhatsappMessage.id).filter(
        WhatsappMessage.appointment_id == appt.id, WhatsappMessage.template_key == wa.T_VISIT_TOKEN,
        WhatsappMessage.token_number == token, WhatsappMessage.status != "cancelled",
        WhatsappMessage.created_by == staff.id, WhatsappMessage.created_at >= now - timedelta(seconds=60),
    ).first()
    if recent:
        return {"token_number": token, "already_existed": existed, "duplicate": True}

    text = wa_appt._token_text(db, appt, hospital, doctor, patient, name, token, checkin)
    open_row = (db.query(WhatsappMessage)
                .filter(WhatsappMessage.appointment_id == appt.id, WhatsappMessage.template_key == wa.T_VISIT_TOKEN,
                        WhatsappMessage.status.in_(wa.OPEN_STATUSES))
                .order_by(WhatsappMessage.id.desc()).first())
    if open_row is not None:
        # The waiting token message is brought forward instead of adding a second one.
        open_row.message_text, open_row.token_number = text, token
        if checkin is not None:
            open_row.checkin_id = checkin.id
        if open_row.status == "scheduled":
            open_row.status, open_row.status_changed_at = "pending", now
        if open_row.due_at > now:
            open_row.due_at = now
        open_row.created_by = staff.id
        db.flush()
    else:
        wa.enqueue_message(
            db, template_key=wa.T_VISIT_TOKEN, text=text, token_number=token,
            checkin_id=checkin.id if checkin else None,
            expires_at=wa_appt._expiry(appt.requested_time, now, wa_appt.TOKEN_VALID_AFTER),
            **wa_appt._common(appt, account, patient, name, staff.id))
    return {"token_number": token, "already_existed": existed, "duplicate": False}