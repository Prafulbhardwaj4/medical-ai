from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.doctor import Doctor
from app.models.doctor_slot import DoctorSlot
from app.models.hospital import Hospital
from app.models.portal import Appointment, AppointmentStatus, PatientAccount
from app.routers.portal_appointments import (
    _check_no_duplicate_active_booking, _ensure_slot_bookable, _estimated_slot_datetime, _release_abandoned_holds,
)
from app.routers.portal_appointments_staff import _park_stale_checkin
from app.services import reception_appointments as ra
from app.services import whatsapp_messages as wa
from app.services.whatsapp_appointments import queue_appointment_cancelled, queue_appointment_rescheduled
from app.utils.audit import stage_action
from app.utils.auth import get_current_doctor
from app.utils.notify import resolve_notification
from app.utils.portal_billing import current_doctor_fee
from app.utils.timezone import now_ist_naive

router = APIRouter(prefix="/portal-appointments-staff", tags=["portal-appointments-reception"])

_STAFF_ROLES = ["admin", "sub_admin", "receptionist"]


class ReceptionCancelIn(BaseModel):
    reason: str
    note: Optional[str] = None
    expected_requested_time: Optional[str] = None


class ReceptionRescheduleIn(BaseModel):
    slot_id: int
    doctor_id: Optional[int] = None
    note: Optional[str] = None
    expected_requested_time: Optional[str] = None


class ResendTokenIn(BaseModel):
    expected_requested_time: Optional[str] = None


def _require_staff(current_doctor) -> None:
    if current_doctor.role.value not in _STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")


def _doctor_label(db: Session, doctor_id: Optional[int]) -> str:
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first() if doctor_id else None
    return f"{doctor.title} {doctor.name}".strip() if doctor else "Unassigned"


def _commit_or_fail(db: Session, what: str) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Could not {what}. Nothing was changed. Please try again.")


def _clear_review_state(db: Session, appt: Appointment) -> None:
    appt.review_deadline_at = None
    appt.review_followup_sent_at = None
    appt.reschedule_kind = None
    appt.requested_reschedule_slot_id = None
    resolve_notification(db, appt.hospital_id, f"appointment_needs_review:{appt.id}")
    resolve_notification(db, appt.hospital_id, f"appointment_reschedule_requested:{appt.id}")


@router.get("/{appointment_id}/cancel-preview")
def reception_cancel_preview(
    appointment_id: int,
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """What a cancellation would refund, shown on the confirm step before anything is changed."""
    _require_staff(current_doctor)
    appt = db.query(Appointment).filter(
        Appointment.id == appointment_id, Appointment.hospital_id == current_doctor.hospital_id
    ).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    why = ra.block_reason(db, appt)
    paid = ra.paid_amount(db, appt)
    return {
        "can_cancel": why is None,
        "blocked_reason": why,
        "patient_name": ra.patient_name(appt),
        "doctor_name": _doctor_label(db, appt.doctor_id),
        "requested_time": appt.requested_time.isoformat(),
        "paid": appt.payment_status == "paid",
        "refund_amount": paid,
        "refund_method": ra.default_channel(appt) if paid > 0 else None,
        "reasons": [{"value": k, "label": v} for k, v in ra.CANCEL_REASONS.items()],
    }


@router.post("/{appointment_id}/cancel")
def reception_cancel_appointment(
    appointment_id: int,
    body: ReceptionCancelIn,
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """Reception cancels any appointment of its own hospital. Everything the patient paid is refunded in full
    (a pending refund, paid out from the Refunds page); the slot is released; unsent messages are cancelled and
    the cancellation message is created; one audit entry is saved in the same transaction."""
    _require_staff(current_doctor)
    label = ra.reason_label(body.reason)
    note = ra.clean_note(body.note)

    appt = ra.lock_appointment(db, appointment_id, current_doctor.hospital_id)
    ra.refuse_if_changed(appt, body.expected_requested_time)
    ra.require_actionable(db, appt)

    old_status = appt.status.value
    paid = ra.paid_amount(db, appt)
    reason_text = f"{ra.CANCEL_REFUND_PREFIX}: {label}" + (f" - {note}" if note else "")

    # A fee difference that was only ever owed (never collected) disappears with the appointment.
    for charge in ra.unpaid_difference_charges(db, appt):
        db.delete(charge)
    refund = ra.add_refund(db, appt, paid, reason_text, current_doctor, cap=paid)

    ra.release_slot(db, appt.slot_id)
    _park_stale_checkin(db, appt, detach=False)

    appt.status = AppointmentStatus.cancelled
    appt.cancelled_by = "reception"
    appt.reschedule_balance_due = None
    appt.mass_reschedule_notice = False
    _clear_review_state(db, appt)
    if appt.payment_status != "paid":
        # An unpaid booking stays on Pending Appointment Reviews for 24 hours, so reception can still give the
        # patient another day. The same column holds the end of that window while the booking is cancelled.
        appt.review_deadline_at = now_ist_naive() + timedelta(hours=24)
    queue_appointment_cancelled(db, appt, created_by=current_doctor.id, commit=False)  # unsent messages cancelled + "cancelled" message

    stage_action(
        db, current_doctor, action="appointment_cancelled_by_reception", target_type="appointment", target_id=appt.id,
        target_label=ra.patient_name(appt)[:120],
        details=(f"status {old_status} -> cancelled, was {appt.requested_time.isoformat()} with {_doctor_label(db, appt.doctor_id)}. "
                 f"Reason: {label}" + (f" ({note})" if note else "") +
                 f". Refund: Rs.{(refund.amount if refund else 0):.2f}" + (f" by {refund.channel}, refund #{refund.id}" if refund else " (nothing paid)"))[:1500],
    )
    _commit_or_fail(db, "cancel this appointment")
    return {
        "message": "Appointment cancelled." + (f" A refund of Rs.{refund.amount:.2f} is waiting on the Refunds page." if refund else ""),
        "refund_amount": refund.amount if refund else 0,
        "refund_id": refund.id if refund else None,
    }


@router.post("/{appointment_id}/reschedule")
def reception_reschedule_appointment(
    appointment_id: int,
    body: ReceptionRescheduleIn,
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """Reception moves an appointment to another slot of the same doctor, or of another doctor of the same hospital.
    The payment already made is kept. The new time is treated as a new appointment for the messages (confirmation,
    24-hour reminder, token), and the old time gets the "rescheduled" message."""
    _require_staff(current_doctor)
    note = ra.clean_note(body.note)

    appt = ra.lock_appointment(db, appointment_id, current_doctor.hospital_id)
    ra.refuse_if_changed(appt, body.expected_requested_time)
    ra.require_actionable(db, appt)

    # Slots are locked in id order (old and new together) so two receptionists can never deadlock each other.
    slot_ids = sorted({i for i in (appt.slot_id, body.slot_id) if i})
    locked = {s.id: s for s in db.query(DoctorSlot).filter(DoctorSlot.id.in_(slot_ids)).order_by(DoctorSlot.id).with_for_update().all()}
    new_slot = locked.get(body.slot_id)
    if not new_slot or new_slot.hospital_id != appt.hospital_id:
        raise HTTPException(status_code=404, detail="That time slot was not found")
    if body.doctor_id and body.doctor_id != new_slot.doctor_id:
        raise HTTPException(status_code=400, detail="That time slot does not belong to the chosen doctor")
    if new_slot.id == appt.slot_id:
        raise HTTPException(status_code=400, detail="Pick a different time slot")

    new_doctor = db.query(Doctor).filter(
        Doctor.id == new_slot.doctor_id, Doctor.hospital_id == appt.hospital_id, Doctor.is_active == True  # noqa: E712
    ).first()
    if not new_doctor:
        raise HTTPException(status_code=400, detail="That doctor is not available in this hospital")
    if not db.query(Hospital.id).filter(Hospital.id == appt.hospital_id, Hospital.is_active == True).first():  # noqa: E712
        raise HTTPException(status_code=400, detail="This hospital is not active")

    _ensure_slot_bookable(db, new_slot, appt.hospital_id)  # same hospital, not over, doctor not on leave that day
    _release_abandoned_holds(db, new_slot)
    now = now_ist_naive()
    if new_slot.booked_count >= new_slot.capacity:
        raise HTTPException(status_code=400, detail="That time slot is full. Please pick another.")
    if _estimated_slot_datetime(new_slot, new_slot.booked_count + 1) <= now:
        raise HTTPException(status_code=400, detail="That time has already passed. Please pick a later slot.")

    doctor_changed = new_slot.doctor_id != appt.doctor_id
    if doctor_changed:
        account = db.query(PatientAccount).filter(PatientAccount.id == appt.account_id).first()
        try:
            _check_no_duplicate_active_booking(db, account, appt.profile_link_id, appt.new_patient_name, new_slot.doctor_id)
        except HTTPException:
            raise HTTPException(status_code=400, detail="This patient already has an active appointment with that doctor.")

    old_time, old_doctor_id, old_status = appt.requested_time, appt.doctor_id, appt.status.value
    old_fee = float(appt.fee_amount or 0)

    # Money first, while the old visit is still attached to the appointment.
    refund = None
    balance_due = appt.reschedule_balance_due
    if appt.payment_status == "paid" and doctor_changed:
        paid = ra.paid_amount(db, appt)
        for charge in ra.unpaid_difference_charges(db, appt):
            db.delete(charge)
        new_fee = float(current_doctor_fee(db, new_slot.doctor_id) or 0)
        if new_fee > paid:
            balance_due = round(new_fee - paid, 2)  # collected at payment, like any other balance
        else:
            balance_due = None
            if new_fee < paid:
                refund = ra.add_refund(
                    db, appt, round(paid - new_fee, 2),
                    f"Rescheduled by reception to a lower-fee doctor (Rs.{paid:.2f} -> Rs.{new_fee:.2f}) on {now.strftime('%Y-%m-%d %H:%M:%S')}",
                    current_doctor, cap=paid)
        appt.fee_amount = new_fee
        appt.reschedule_balance_due = balance_due

    ra.take_slot_place(db, new_slot)
    ra.release_slot(db, appt.slot_id)
    new_time = _estimated_slot_datetime(new_slot, new_slot.booked_count)

    # The old token (if one was made) is taken out of the doctor's way; its fee moves with the appointment.
    _park_stale_checkin(db, appt, detach=True)

    appt.slot_id = new_slot.id
    appt.doctor_id = new_slot.doctor_id
    appt.requested_time = new_time
    if appt.status == AppointmentStatus.pending_review:
        appt.status = AppointmentStatus.confirmed if appt.payment_status == "paid" else AppointmentStatus.booked
    # A patient who is already here keeps the arrival when the new time is today and they are not late for it.
    keep_arrival = bool(
        appt.arrived_at and appt.arrived_at.date() == new_time.date()
        and appt.arrived_at <= new_time + timedelta(minutes=settings.PORTAL_PAYMENT_GRACE_MINUTES)
    )
    if not keep_arrival:
        appt.arrived_at = None
    appt.no_show_detected_at = None
    appt.no_show_reason = None
    appt.no_show_reschedule_deadline = None
    appt.mass_reschedule_notice = False
    _clear_review_state(db, appt)
    queue_appointment_rescheduled(db, appt, old_time, old_doctor_id=old_doctor_id, created_by=current_doctor.id, commit=False)

    stage_action(
        db, current_doctor, action="appointment_rescheduled_by_reception", target_type="appointment", target_id=appt.id,
        target_label=ra.patient_name(appt)[:120],
        details=(f"{old_time.isoformat()} ({_doctor_label(db, old_doctor_id)}) -> {new_time.isoformat()} ({_doctor_label(db, appt.doctor_id)}), "
                 f"status {old_status} -> {appt.status.value}, fee Rs.{old_fee:.2f} -> Rs.{float(appt.fee_amount or 0):.2f}"
                 + (f", refund Rs.{refund.amount:.2f} (#{refund.id})" if refund else "")
                 + (f", balance due Rs.{balance_due:.2f}" if balance_due else "")
                 + (f". Note: {note}" if note else ""))[:1500],
    )
    _commit_or_fail(db, "reschedule this appointment")
    return {
        "message": "Appointment rescheduled." + (f" A refund of Rs.{refund.amount:.2f} is waiting on the Refunds page." if refund else "")
                   + (f" Rs.{balance_due:.2f} more is due at payment." if balance_due else ""),
        "requested_time": new_time.isoformat(),
        "doctor_id": appt.doctor_id,
        "doctor_name": _doctor_label(db, appt.doctor_id),
        "refund_amount": refund.amount if refund else 0,
        "balance_due": balance_due or 0,
        "arrived_at": appt.arrived_at.isoformat() if appt.arrived_at else None,
    }


class ReceptionRebookIn(BaseModel):
    slot_id: int
    doctor_id: Optional[int] = None
    note: Optional[str] = None


@router.post("/{appointment_id}/rebook-after-cancel")
def reception_rebook_after_cancel(
    appointment_id: int,
    body: ReceptionRebookIn,
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """A patient whose UNPAID booking reception just cancelled asks for another day. Allowed for 24 hours after the
    cancellation. The booking becomes a normal unpaid booking at the new time, with its own confirmation, reminder
    and token messages. Nothing was paid, so there is no money to move."""
    _require_staff(current_doctor)
    note = ra.clean_note(body.note)

    appt = ra.lock_appointment(db, appointment_id, current_doctor.hospital_id)
    now = now_ist_naive()
    if (appt.status != AppointmentStatus.cancelled or appt.cancelled_by != "reception" or appt.payment_status == "paid"
            or not appt.review_deadline_at or appt.review_deadline_at <= now):
        raise HTTPException(status_code=400, detail="This appointment can no longer be rescheduled from here. Please make a new booking.")

    new_slot = db.query(DoctorSlot).filter(DoctorSlot.id == body.slot_id).with_for_update().first()
    if not new_slot or new_slot.hospital_id != appt.hospital_id:
        raise HTTPException(status_code=404, detail="That time slot was not found")
    if body.doctor_id and body.doctor_id != new_slot.doctor_id:
        raise HTTPException(status_code=400, detail="That time slot does not belong to the chosen doctor")
    new_doctor = db.query(Doctor).filter(
        Doctor.id == new_slot.doctor_id, Doctor.hospital_id == appt.hospital_id, Doctor.is_active == True  # noqa: E712
    ).first()
    if not new_doctor:
        raise HTTPException(status_code=400, detail="That doctor is not available in this hospital")
    if not db.query(Hospital.id).filter(Hospital.id == appt.hospital_id, Hospital.is_active == True).first():  # noqa: E712
        raise HTTPException(status_code=400, detail="This hospital is not active")

    _ensure_slot_bookable(db, new_slot, appt.hospital_id)  # same hospital, not over, doctor not on leave that day
    _release_abandoned_holds(db, new_slot)
    if new_slot.booked_count >= new_slot.capacity:
        raise HTTPException(status_code=400, detail="That time slot is full. Please pick another.")
    if _estimated_slot_datetime(new_slot, new_slot.booked_count + 1) <= now:
        raise HTTPException(status_code=400, detail="That time has already passed. Please pick a later slot.")

    account = db.query(PatientAccount).filter(PatientAccount.id == appt.account_id).first()
    try:
        _check_no_duplicate_active_booking(db, account, appt.profile_link_id, appt.new_patient_name, new_slot.doctor_id)
    except HTTPException:
        raise HTTPException(status_code=400, detail="This patient already has an active appointment with that doctor.")

    old_time, old_doctor_id = appt.requested_time, appt.doctor_id
    doctor_changed = new_slot.doctor_id != appt.doctor_id

    ra.take_slot_place(db, new_slot)
    new_time = _estimated_slot_datetime(new_slot, new_slot.booked_count)
    appt.slot_id = new_slot.id
    appt.doctor_id = new_slot.doctor_id
    appt.requested_time = new_time
    appt.status = AppointmentStatus.booked
    appt.cancelled_by = None
    appt.review_deadline_at = None
    appt.arrived_at = None
    if doctor_changed:
        appt.fee_amount = None  # the new doctor's fee is picked up when the payment is collected

    # The "cancelled" message, if it has not gone out yet, is replaced by the "rescheduled" one.
    wa.cancel_unsent(db, appointment_id=appt.id, template_keys=[wa.T_APPT_CANCELLED])
    queue_appointment_rescheduled(db, appt, old_time, old_doctor_id=old_doctor_id, created_by=current_doctor.id, commit=False)

    stage_action(
        db, current_doctor, action="appointment_rebooked_after_cancel", target_type="appointment", target_id=appt.id,
        target_label=ra.patient_name(appt)[:120],
        details=(f"cancelled booking of {old_time.isoformat()} ({_doctor_label(db, old_doctor_id)}) moved to "
                 f"{new_time.isoformat()} ({_doctor_label(db, appt.doctor_id)}), still unpaid"
                 + (f". Note: {note}" if note else ""))[:1500],
    )
    _commit_or_fail(db, "reschedule this appointment")
    return {
        "message": "Appointment rescheduled. It is back in Pending Appointment Reviews until payment is collected.",
        "requested_time": new_time.isoformat(),
        "doctor_id": appt.doctor_id,
        "doctor_name": _doctor_label(db, appt.doctor_id),
    }


@router.post("/{appointment_id}/resend-token")
def reception_resend_token(
    appointment_id: int,
    body: Optional[ResendTokenIn] = None,
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """For a patient who says the token never arrived: the SAME token is sent again (made first if it does not exist
    yet). It does not mark the patient as arrived and takes no payment."""
    _require_staff(current_doctor)
    appt = ra.lock_appointment(db, appointment_id, current_doctor.hospital_id)
    ra.refuse_if_changed(appt, body.expected_requested_time if body else None)
    result = ra.resend_token_message(db, appt, current_doctor)
    if not result["duplicate"]:
        stage_action(
            db, current_doctor, action="appointment_token_resent", target_type="appointment", target_id=appt.id,
            target_label=ra.patient_name(appt)[:120],
            details=f"token {result['token_number']} " + ("sent again" if result["already_existed"] else "generated and sent"),
        )
    _commit_or_fail(db, "send the token")
    return {
        "token_number": result["token_number"],
        "message": f"Token {result['token_number']} sent to the messages list",
    }