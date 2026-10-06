from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.models.portal import Appointment, AppointmentStatus
from app.models.doctor import Doctor
from app.models.hospital import Hospital
from app.models.doctor_slot import DoctorSlot
from app.models.notification import Notification
from app.schemas.patient import PaymentMethodIn, CollectAppointmentPaymentIn
from app.models.patient import Patient
from app.schemas.portal import DeclineAppointmentIn, SuggestAppointmentIn
from app.utils.auth import get_current_doctor
from app.utils.timezone import now_ist_naive
from app.utils.portal_billing import current_doctor_fee, create_patient_cancellation_refund
from app.utils.notify import resolve_notification
from app.utils.portal_checkin import convert_appointment_to_checkin
from app.utils.portal_auth import hash_password
from app.models.portal import PatientAccount, PatientProfileLink
from app.routers.portal_appointments import _estimated_slot_datetime, _release_abandoned_holds, _check_no_duplicate_active_booking, _reassign_late_arrival_slot
from app.schemas.portal import BookForCallerIn
import random
import string
from app.utils.audit import log_action
from app.utils.phone import normalize_phone

router = APIRouter(prefix="/portal-appointments-staff", tags=["portal-appointments-staff"])

_STAFF_ROLES = ["admin", "sub_admin", "receptionist"]
_APPT_VIEW_ROLES = ["admin", "sub_admin", "receptionist", "doctor", "nurse", "assistant"]


@router.post("/book-for-caller", response_model=None)
def book_appointment_for_caller(
    body: BookForCallerIn,
    current_doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """Reception books an online-appointment slot for someone who called in,
    using the exact same slot capacity/locking machinery the patient portal
    itself uses (see book_appointment in portal_appointments.py) — so a
    phone-booked slot and a portal-booked slot are indistinguishable to
    every doctor/queue view downstream. Reception has already resolved a
    real hospital patient_id before calling this (existing patient picked,
    or a new one just registered via the normal /patients/ flow), so this
    links straight to that record via profile_link_id — no deferred
    new_patient_name and no temporary portal password to read out. Portal
    login credentials for phone bookings are on hold until the WhatsApp
    channel is in place to deliver them properly."""
    if current_doctor.role.value not in _STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")

    patient = db.query(Patient).filter(
        Patient.id == body.patient_id, Patient.hospital_id == current_doctor.hospital_id
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    link = db.query(PatientProfileLink).filter(PatientProfileLink.patient_id == patient.id).first()
    if not link:
        _acct_phone = normalize_phone(patient.phone)
        if len(_acct_phone) != 10:
            raise HTTPException(status_code=400, detail="This patient's phone number is invalid. Correct it on the patient record before booking.")
        account = db.query(PatientAccount).filter(PatientAccount.phone == _acct_phone).first()
        if not account:
            # Not a real login yet — portal password delivery is on hold
            # until WhatsApp is wired up, so this is just an internal,
            # unshared placeholder that satisfies the not-null column.
            placeholder_password = "".join(random.choices(string.ascii_letters + string.digits, k=24))
            account = PatientAccount(phone=_acct_phone, password_hash=hash_password(placeholder_password))
            db.add(account)
            db.flush()
        link = PatientProfileLink(account_id=account.id, patient_id=patient.id, relation="self")
        db.add(link)
        db.flush()

    account = db.query(PatientAccount).filter(PatientAccount.id == link.account_id).first()

    slot = db.query(DoctorSlot).filter(
        DoctorSlot.id == body.slot_id, DoctorSlot.hospital_id == current_doctor.hospital_id
    ).with_for_update().first()
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")

    _release_abandoned_holds(db, slot)

    if slot.booked_count >= slot.capacity:
        raise HTTPException(status_code=400, detail="This slot just filled up. Please pick another.")

    from app.models.doctor_availability import DoctorUnavailability
    if db.query(DoctorUnavailability).filter(
        DoctorUnavailability.doctor_id == slot.doctor_id, DoctorUnavailability.date == slot.slot_date
    ).first():
        raise HTTPException(status_code=400, detail="This doctor is unavailable on this date. Please pick another date or doctor.")

    _check_no_duplicate_active_booking(db, account, link.id, None, slot.doctor_id)

    slot.booked_count += 1
    requested_time = _estimated_slot_datetime(slot, slot.booked_count)

    appt = Appointment(
        account_id=account.id,
        profile_link_id=link.id,
        hospital_id=current_doctor.hospital_id,
        doctor_id=slot.doctor_id,
        slot_id=slot.id,
        type="scheduled",
        requested_time=requested_time,
        notes=body.notes,
        status=AppointmentStatus.booked,
        payment_status="unpaid",
        address=body.address,
    )
    db.add(appt)
    db.commit()
    db.refresh(appt)

    log_action(
        db, current_doctor,
        action="appointment_booked_for_caller",
        target_type="appointment",
        target_id=appt.id,
        target_label=f"{patient.name} ({patient.patient_uid})",
        details=f"Slot {slot.slot_date} {slot.slot_time}, doctor_id {slot.doctor_id}, status booked/unpaid",
    )

    return {
        "appointment_id": appt.id,
        "estimated_time": requested_time.isoformat(),
        "patient_name": patient.name,
    }


@router.get("/{appointment_id}/payment-timing")
def payment_timing(
    appointment_id: int,
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """Tells reception, before taking money, whether this payment is inside the
    keep-the-same-slot window. Same rule for online and phone bookings."""
    if current_doctor.role.value not in _STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")
    appt = db.query(Appointment).filter(
        Appointment.id == appointment_id, Appointment.hospital_id == current_doctor.hospital_id
    ).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    grace_until = appt.requested_time + timedelta(minutes=settings.PORTAL_PAYMENT_GRACE_MINUTES)
    return {
        "late": bool(appt.slot_id and now_ist_naive() > grace_until),
        "grace_minutes": settings.PORTAL_PAYMENT_GRACE_MINUTES,
        "slot_time": appt.requested_time.isoformat(),
        "grace_until": grace_until.isoformat(),
        "doctor_id": appt.doctor_id,
        "hospital_id": appt.hospital_id,
    }


def _late_unresolved(appt) -> bool:
    """True when the patient arrived more than PORTAL_PAYMENT_GRACE_MINUTES after their
    booked slot and reception has not yet chosen walk-in or a new slot."""
    return bool(
        appt.slot_id and appt.arrived_at
        and appt.arrived_at > appt.requested_time + timedelta(minutes=settings.PORTAL_PAYMENT_GRACE_MINUTES)
    )


from pydantic import BaseModel as _LABaseModel


class LateArrivalIn(_LABaseModel):
    late_choice: str          # "walk_in" | "next_slot"
    slot_id: int = None       # required for "next_slot"


@router.post("/{appointment_id}/arrived-before-payment")
def mark_arrived_before_payment(
    appointment_id: int,
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """Step 1 at reception (until a payment gateway exists): record that the patient
    is here. The arrival time is compared with the booked slot. On time -> collect
    payment. Late -> reception must choose walk-in queue or a new slot BEFORE any
    money is taken."""
    if current_doctor.role.value not in _STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")
    appt = db.query(Appointment).filter(
        Appointment.id == appointment_id, Appointment.hospital_id == current_doctor.hospital_id
    ).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status != AppointmentStatus.booked or appt.payment_status == "paid":
        raise HTTPException(status_code=400, detail="This appointment is not waiting for payment")
    if not appt.arrived_at:
        appt.arrived_at = now_ist_naive()
        db.commit()
        log_action(
            db, current_doctor, action="appointment_arrived_before_payment",
            target_type="appointment", target_id=appt.id,
            details=f"slot {appt.requested_time.isoformat()}, arrived {appt.arrived_at.isoformat()}",
        )
    return {
        "late": _late_unresolved(appt),
        "arrived_at": appt.arrived_at.isoformat(),
        "slot_time": appt.requested_time.isoformat(),
        "grace_minutes": settings.PORTAL_PAYMENT_GRACE_MINUTES,
        "doctor_id": appt.doctor_id,
        "hospital_id": appt.hospital_id,
    }


@router.post("/{appointment_id}/late-arrival")
def resolve_late_arrival(
    appointment_id: int,
    body: LateArrivalIn,
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """Step 2 for a late patient, still BEFORE payment: walk-in queue, or the next
    available slot (today or a later day). If the patient refuses both, nothing is
    collected and the booking simply stays unpaid."""
    if current_doctor.role.value not in _STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")
    appt = db.query(Appointment).filter(
        Appointment.id == appointment_id, Appointment.hospital_id == current_doctor.hospital_id
    ).with_for_update().first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status != AppointmentStatus.booked or appt.payment_status == "paid":
        raise HTTPException(status_code=400, detail="This appointment is not waiting for payment")
    if not _late_unresolved(appt):
        raise HTTPException(status_code=400, detail="This patient is not late, so no slot change is needed")

    now = now_ist_naive()
    choice = (body.late_choice or "").strip()
    old_slot = db.query(DoctorSlot).filter(DoctorSlot.id == appt.slot_id).with_for_update().first()

    if choice == "next_slot":
        if not body.slot_id:
            raise HTTPException(status_code=400, detail="Pick the new slot for this patient")
        new_slot = db.query(DoctorSlot).filter(
            DoctorSlot.id == body.slot_id, DoctorSlot.hospital_id == current_doctor.hospital_id
        ).with_for_update().first()
        if not new_slot:
            raise HTTPException(status_code=404, detail="Slot not found")
        if new_slot.doctor_id != appt.doctor_id:
            raise HTTPException(status_code=400, detail="Pick a slot of the same doctor")
        if new_slot.id == appt.slot_id:
            raise HTTPException(status_code=400, detail="Pick a different slot. The booked one is too late now")
        from app.routers.portal_appointments import _ensure_slot_bookable
        _ensure_slot_bookable(db, new_slot, current_doctor.hospital_id)
        _release_abandoned_holds(db, new_slot)
        if new_slot.booked_count >= new_slot.capacity:
            raise HTTPException(status_code=400, detail="That slot is already full")
        if old_slot and old_slot.booked_count > 0:
            old_slot.booked_count -= 1
        new_slot.booked_count += 1
        appt.slot_id = new_slot.id
        appt.requested_time = _estimated_slot_datetime(new_slot, new_slot.booked_count)
        # arrived_at stays: the patient is here now, which is before the new slot.
    elif choice == "walk_in":
        if old_slot and old_slot.booked_count > 0:
            old_slot.booked_count -= 1
        appt.slot_id = None
        appt.requested_time = now
        appt.arrived_at = now
    else:
        raise HTTPException(status_code=400, detail="Choose the walk-in queue or a new slot")

    db.commit()
    log_action(
        db, current_doctor, action=f"appointment_late_arrival_{choice}",
        target_type="appointment", target_id=appt.id,
        details=f"now {appt.requested_time.isoformat()}",
    )
    return {"message": "Walk-in queue chosen" if choice == "walk_in" else "New slot booked", "requested_time": appt.requested_time.isoformat()}


@router.post("/{appointment_id}/collect-payment")
def collect_payment_at_reception(
    appointment_id: int,
    body: CollectAppointmentPaymentIn,
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """Reception collects payment in person once the caller/walk-in for a
    phone-booked (or portal-booked) appointment actually shows up — there's
    no live payment gateway, so this is the counterpart to the patient
    portal's own mark_paid. If they're paying after their originally
    estimated slot time has already passed, their old slot is released and
    they're bumped to the next available slot for the same doctor today,
    instead of keeping a time that's already gone by."""
    if current_doctor.role.value not in _STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")

    appt = db.query(Appointment).filter(
        Appointment.id == appointment_id, Appointment.hospital_id == current_doctor.hospital_id
    ).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status == AppointmentStatus.cancelled:
        raise HTTPException(status_code=400, detail="Cannot collect payment for a cancelled appointment")
    if appt.payment_status == "paid":
        raise HTTPException(status_code=400, detail="Payment already collected for this appointment")

    now = now_ist_naive()
    reassigned = False
    late_choice_used = None
    # Order is: patient arrived -> (if late: walk-in queue or new slot) -> payment LAST.
    if not appt.arrived_at:
        raise HTTPException(status_code=400, detail="Mark the patient as arrived first. Payment is collected after arrival is recorded.")
    if _late_unresolved(appt):
        raise HTTPException(status_code=400, detail="The patient arrived late. Choose the walk-in queue or a new date and slot first. Payment is collected last.")

    from app.utils.portal_billing import current_doctor_fee
    if body.fee_amount is not None:
        if body.fee_amount < 0:
            raise HTTPException(status_code=400, detail="Fee amount cannot be negative")
        appt.fee_amount = body.fee_amount
    elif appt.doctor_id:
        appt.fee_amount = current_doctor_fee(db, appt.doctor_id)

    appt.payment_status = "paid"
    appt.payment_method = body.payment_method
    appt.paid_at = now

    needs_review = False
    if appt.doctor_id:
        from app.models.doctor_availability import DoctorUnavailability
        needs_review = db.query(DoctorUnavailability).filter(
            DoctorUnavailability.doctor_id == appt.doctor_id,
            DoctorUnavailability.date == appt.requested_time.date(),
        ).first() is not None

    if needs_review:
        appt.status = AppointmentStatus.pending_review
        appt.review_deadline_at = now + timedelta(minutes=settings.PORTAL_REVIEW_RESPONSE_MINUTES)
        db.add(Notification(
            hospital_id=appt.hospital_id,
            source_key=f"appointment_needs_review:{appt.id}",
            type="appointment_needs_review",
            severity="warning",
            title="Appointment needs review",
            message=f"Appointment #{appt.id}'s doctor became unavailable after booking. Accept, suggest a change, or decline.",
            link_type="portal_appointment", link_id=appt.id,
        ))
    else:
        appt.status = AppointmentStatus.confirmed

    db.commit()
    db.refresh(appt)

    log_action(
        db, current_doctor,
        action="appointment_payment_collected",
        target_type="appointment",
        target_id=appt.id,
        details=f"unpaid -> paid via {body.payment_method}, fee Rs.{(appt.fee_amount or 0):.2f}, status -> {appt.status.value}, slot reassigned: {bool(reassigned)}",
    )

    return {
        "message": "Payment collected",
        "reassigned": reassigned,
        "late_choice": late_choice_used,
        "estimated_time": appt.requested_time.isoformat(),
    }


@router.post("/notify-doctor/{doctor_id}")
def notify_doctor_no_assistant(
    doctor_id: int,
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """Reception's 'Notify Doctor' action from Expected Today, for an online
    patient whose doctor has no nurse/assistant currently covering them."""
    if current_doctor.role.value not in _STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")

    doctor = db.query(Doctor).filter(
        Doctor.id == doctor_id,
        Doctor.hospital_id == current_doctor.hospital_id
    ).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    existing = db.query(Notification).filter(
        Notification.hospital_id == current_doctor.hospital_id,
        Notification.source_key == f"no_assistant:{doctor_id}",
        Notification.is_read == False
    ).first()
    if existing:
        existing.updated_at = now_ist_naive()
        db.commit()
        return {"message": "Doctor already notified"}

    notif = Notification(
        hospital_id=current_doctor.hospital_id,
        source_key=f"no_assistant:{doctor_id}",
        type="no_assistant_alert",
        severity="warning",
        title="No assistant available",
        message="A patient is expected and no one is covering your queue for vitals — check them in directly when you're ready.",
        target_doctor_id=doctor_id,
    )
    db.add(notif)
    db.commit()
    return {"message": "Doctor notified"}


def _expire_stale_pending_reviews(db: Session, hospital_id: int) -> None:
    """No background scheduler in this codebase — same lazy-sweep pattern as
    _release_abandoned_holds in portal_appointments.py. Runs whenever staff
    loads the Pending Review list: fires the follow-up alert once the
    response deadline passes, then auto-declines with a full refund if still
    not actioned PORTAL_REVIEW_AUTO_DECLINE_GRACE_MINUTES after that."""
    now = now_ist_naive()
    pending = db.query(Appointment).filter(
        Appointment.hospital_id == hospital_id,
        Appointment.status == AppointmentStatus.pending_review,
    ).all()

    for appt in pending:
        if not appt.review_deadline_at or now < appt.review_deadline_at:
            continue

        if not appt.review_followup_sent_at:
            appt.review_followup_sent_at = now
            db.add(Notification(
                hospital_id=hospital_id,
                source_key=f"appointment_review_followup:{appt.id}",
                type="appointment_review_followup",
                severity="warning",
                title="Appointment review overdue",
                message=f"Appointment #{appt.id} is still awaiting Accept/Suggest/Decline past its response deadline.",
                link_type="portal_appointment", link_id=appt.id,
            ))
            continue

        grace_cutoff = appt.review_followup_sent_at + timedelta(minutes=settings.PORTAL_REVIEW_AUTO_DECLINE_GRACE_MINUTES)
        if now < grace_cutoff:
            continue

        if appt.reschedule_kind == "no_show":
            # No automatic full refund — being late was the patient's
            # responsibility. Admin gets notified reception didn't act, and
            # the patient still gets a reschedule option within their
            # original 72hr window regardless (this just reverts the
            # request, it doesn't forfeit the booking).
            appt.reschedule_kind = None
            appt.requested_reschedule_slot_id = None
            appt.review_deadline_at = None
            appt.review_followup_sent_at = None
            appt.status = AppointmentStatus.confirmed
            db.add(Notification(
                hospital_id=hospital_id,
                source_key=f"appointment_noshow_reschedule_missed:{appt.id}",
                type="appointment_noshow_reschedule_missed",
                severity="critical",
                title="Reception missed a no-show reschedule request",
                message=f"Appointment #{appt.id}'s reschedule request wasn't actioned in time. No refund applied — patient can still request another reschedule within their 72hr window.",
                link_type="portal_appointment", link_id=appt.id,
            ))
            continue

        create_patient_cancellation_refund(
            db, appt, reason="Auto-declined — hospital didn't respond in time", percent=100,
        )
        if appt.slot_id:
            slot = db.query(DoctorSlot).filter(DoctorSlot.id == appt.slot_id).with_for_update().first()
            if slot and slot.booked_count > 0:
                slot.booked_count -= 1
        appt.status = AppointmentStatus.cancelled
        db.add(Notification(
            hospital_id=hospital_id,
            source_key=f"appointment_auto_declined:{appt.id}",
            type="appointment_auto_declined",
            severity="critical",
            title="Appointment auto-declined",
            message=f"Appointment #{appt.id} was auto-declined and fully refunded — no staff action was taken before the deadline.",
            link_type="portal_appointment", link_id=appt.id,
        ))
    db.commit()


def _expire_stale_awaiting_payment(db: Session, hospital_id: int) -> None:
    """Phone bookings reception took (status=booked, payment_status=unpaid)
    stay in Pending Appointment Reviews under reason='awaiting_payment'
    until someone collects payment. If the caller never shows up/pays that
    same day, the booking is a no-show — cancel it (no refund owed, nothing
    was ever paid) and release its slot so it stops sitting in the list as
    a backdated entry. Same-day bookings are left alone even if their exact
    slot time has passed — collect_payment_at_reception already bumps a
    late arrival to the next free slot for today, so only once the day
    itself is over do we give up and clear it out."""
    today_start = datetime.combine(now_ist_naive().date(), datetime.min.time())

    stale = db.query(Appointment).filter(
        Appointment.hospital_id == hospital_id,
        Appointment.status == AppointmentStatus.booked,
        Appointment.payment_status == "unpaid",
        Appointment.requested_time < today_start,
    ).all()

    for appt in stale:
        if appt.slot_id:
            slot = db.query(DoctorSlot).filter(DoctorSlot.id == appt.slot_id).with_for_update().first()
            if slot and slot.booked_count > 0:
                slot.booked_count -= 1
        appt.status = AppointmentStatus.cancelled
        db.add(Notification(
            hospital_id=hospital_id,
            source_key=f"appointment_awaiting_payment_expired:{appt.id}",
            type="appointment_awaiting_payment_expired",
            severity="warning",
            title="Phone booking cancelled — no-show",
            message=f"Appointment #{appt.id} was never paid/collected on its booked day and has been cancelled.",
            link_type="portal_appointment", link_id=appt.id,
        ))
    db.commit()


@router.get("/{appointment_id}/new-patient-prefill")
def new_patient_prefill(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin", "receptionist"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    appt = db.query(Appointment).filter(
        Appointment.id == appointment_id, Appointment.hospital_id == current_doctor.hospital_id
    ).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.profile_link_id:
        raise HTTPException(status_code=400, detail="This booking is already linked to an existing patient record")

    return {
        "name": appt.new_patient_name,
        "gender": appt.new_patient_gender,
        "age": appt.new_patient_age,
        "blood_group": appt.new_patient_blood_group,
        "phone": appt.account.phone if appt.account else None,
        "address": appt.address,
    }


@router.get("/analytics")
def appointment_analytics(
    doctor_id: int = Query(None),
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """Online (portal-booked) appointments, paid, in the last 45 days, grouped by doctor."""
    if current_doctor.role.value not in _APPT_VIEW_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")
    cutoff = now_ist_naive() - timedelta(days=45)

    q = db.query(Appointment).filter(
        Appointment.hospital_id == current_doctor.hospital_id,
        Appointment.payment_status == "paid",
        Appointment.requested_time >= cutoff,
    )
    if doctor_id:
        q = q.filter(Appointment.doctor_id == doctor_id)

    appts = q.all()
    counts = {}
    for a in appts:
        if not a.doctor_id:
            continue
        counts[a.doctor_id] = counts.get(a.doctor_id, 0) + 1

    result = []
    for d_id, count in counts.items():
        doctor = db.query(Doctor).filter(Doctor.id == d_id).first()
        result.append({
            "doctor_id": d_id,
            "doctor_name": f"{doctor.title} {doctor.name}" if doctor else "Unknown",
            "appointment_count": count,
        })
    result.sort(key=lambda x: x["appointment_count"], reverse=True)
    return {"total": len(appts), "by_doctor": result}


from pydantic import BaseModel as _NSBaseModel


class NoShowRebookIn(_NSBaseModel):
    slot_id: int
    note: str = None


class NoShowRefundIn(_NSBaseModel):
    percent: int = 100
    note: str = None


def _noshow_appt_or_404(db: Session, appointment_id: int, hospital_id: int) -> Appointment:
    appt = db.query(Appointment).filter(
        Appointment.id == appointment_id, Appointment.hospital_id == hospital_id
    ).with_for_update().first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if (appt.status != AppointmentStatus.confirmed or appt.payment_status != "paid"
            or not appt.no_show_detected_at):
        raise HTTPException(status_code=400, detail="This is not a paid no-show waiting for action")
    return appt


def _park_stale_checkin(db: Session, appt: Appointment, detach: bool) -> None:
    """The sweep made a token for this appointment on its day. The patient never
    consulted, so take that token out of the doctor's way. For a rebook it is also
    detached (its fee moves to the new token, so money is counted once)."""
    from app.models.checkin import Checkin
    from app.models.consultation import Consultation
    c = db.query(Checkin).filter(Checkin.portal_appointment_id == appt.id).first()
    if not c:
        return
    if db.query(Consultation.id).filter(Consultation.token_number == c.token_number).first():
        return  # already consulted: never touch
    c.up_next_skip = True
    if detach:
        c.portal_appointment_id = None
        c.consultation_fee = 0.0


@router.get("/no-shows")
def list_no_shows(
    days: int = Query(14, ge=1, le=90),
    doctor_id: int = Query(None),
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """Paid appointments the patient did not turn up for. Nothing here is cancelled
    automatically: reception picks Rebook or Refund for each one."""
    if current_doctor.role.value not in _STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")
    from app.utils.portal_noshow import detect_no_shows
    detect_no_shows(db, current_doctor.hospital_id)

    since = now_ist_naive() - timedelta(days=days)
    q = db.query(Appointment).filter(
        Appointment.hospital_id == current_doctor.hospital_id,
        Appointment.status == AppointmentStatus.confirmed,
        Appointment.payment_status == "paid",
        Appointment.no_show_detected_at.isnot(None),
        Appointment.requested_time >= since,
    )
    if doctor_id:
        q = q.filter(Appointment.doctor_id == doctor_id)
    appts = q.order_by(Appointment.requested_time.desc()).all()

    result = []
    for a in appts:
        patient = a.profile_link.patient if a.profile_link_id and a.profile_link and a.profile_link.patient else None
        doctor = db.query(Doctor).filter(Doctor.id == a.doctor_id).first() if a.doctor_id else None
        result.append({
            "id": a.id,
            "hospital_id": a.hospital_id,
            "doctor_id": a.doctor_id,
            "doctor_name": f"{doctor.title} {doctor.name}" if doctor else "Unassigned",
            "patient_name": patient.name if patient else (a.new_patient_name or "Unknown"),
            "patient_uid": patient.patient_uid if patient else None,
            "requested_time": a.requested_time.isoformat(),
            "no_show_detected_at": a.no_show_detected_at.isoformat(),
            "no_show_reason": a.no_show_reason,
            "fee_amount": a.fee_amount,
            "payment_method": a.payment_method,
        })
    return {"count": len(result), "appointments": result}


@router.post("/{appointment_id}/no-show/rebook")
def rebook_no_show(
    appointment_id: int,
    body: NoShowRebookIn,
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """Move a paid no-show to a later slot of the SAME doctor. The fee already paid
    carries over, so no new charge and no refund."""
    if current_doctor.role.value not in _STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")
    appt = _noshow_appt_or_404(db, appointment_id, current_doctor.hospital_id)

    new_slot = db.query(DoctorSlot).filter(
        DoctorSlot.id == body.slot_id, DoctorSlot.hospital_id == appt.hospital_id
    ).with_for_update().first()
    if not new_slot:
        raise HTTPException(status_code=404, detail="Slot not found")
    if new_slot.doctor_id != appt.doctor_id:
        raise HTTPException(status_code=400, detail="Rebook is for the same doctor. To change doctor, use Refund and book again.")
    if new_slot.slot_date <= now_ist_naive().date():
        raise HTTPException(status_code=400, detail="Pick a slot on a later day")
    from app.routers.portal_appointments import _ensure_slot_bookable
    _ensure_slot_bookable(db, new_slot, appt.hospital_id)
    _release_abandoned_holds(db, new_slot)
    if new_slot.booked_count >= new_slot.capacity:
        raise HTTPException(status_code=400, detail="That slot is already full")

    old_time = appt.requested_time
    if appt.slot_id:
        old_slot = db.query(DoctorSlot).filter(DoctorSlot.id == appt.slot_id).with_for_update().first()
        if old_slot and old_slot.booked_count > 0:
            old_slot.booked_count -= 1
    new_slot.booked_count += 1
    appt.slot_id = new_slot.id
    appt.requested_time = _estimated_slot_datetime(new_slot, new_slot.booked_count)

    _park_stale_checkin(db, appt, detach=True)

    appt.arrived_at = None
    appt.no_show_detected_at = None
    appt.no_show_reason = None
    appt.no_show_reschedule_deadline = None
    appt.reschedule_kind = None
    appt.requested_reschedule_slot_id = None
    db.commit()
    log_action(
        db, current_doctor,
        action="appointment_noshow_rebooked",
        target_type="appointment", target_id=appt.id,
        details=f"{old_time.isoformat()} -> {appt.requested_time.isoformat()}" + (f". Note: {body.note}" if body.note else ""),
    )
    return {"message": "Rebooked. The fee already paid carries over.", "requested_time": appt.requested_time.isoformat()}


@router.post("/{appointment_id}/no-show/refund")
def refund_no_show(
    appointment_id: int,
    body: NoShowRefundIn,
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """Cancel a paid no-show and refund through the normal refund flow (pending refund
    that reception settles from the Refunds list)."""
    if current_doctor.role.value not in _STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")
    if body.percent < 1 or body.percent > 100:
        raise HTTPException(status_code=400, detail="Refund percent must be between 1 and 100")
    appt = _noshow_appt_or_404(db, appointment_id, current_doctor.hospital_id)

    create_patient_cancellation_refund(
        db, appt, reason="No-show refund approved by reception", percent=body.percent,
    )
    if appt.slot_id:
        slot = db.query(DoctorSlot).filter(DoctorSlot.id == appt.slot_id).with_for_update().first()
        if slot and slot.booked_count > 0:
            slot.booked_count -= 1
    _park_stale_checkin(db, appt, detach=False)
    appt.status = AppointmentStatus.cancelled
    db.commit()
    log_action(
        db, current_doctor,
        action="appointment_noshow_refunded",
        target_type="appointment", target_id=appt.id,
        details=f"{body.percent}% of Rs.{(appt.fee_amount or 0):.2f}" + (f". Note: {body.note}" if body.note else ""),
    )
    return {"message": "Cancelled. A refund is pending in the Refunds list."}


@router.get("/today")
def list_expected_today(
    doctor_id: int = Query(None),
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    if current_doctor.role.value not in _APPT_VIEW_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")
    from app.utils.portal_checkin import sweep_todays_online_checkins
    from app.utils.portal_noshow import detect_no_shows
    sweep_todays_online_checkins(db, current_doctor.hospital_id)
    detect_no_shows(db, current_doctor.hospital_id)

    today_start = datetime.combine(now_ist_naive().date(), datetime.min.time())
    today_end = today_start + timedelta(days=1)

    q = db.query(Appointment).filter(
        Appointment.hospital_id == current_doctor.hospital_id,
        Appointment.status.in_([AppointmentStatus.confirmed, AppointmentStatus.completed]),
        Appointment.requested_time >= today_start,
        Appointment.requested_time < today_end,
    )
    if doctor_id:
        q = q.filter(Appointment.doctor_id == doctor_id)

    appts = q.order_by(Appointment.requested_time).all()

    result = []
    for a in appts:
        patient_id = None
        patient_uid = None
        patient_name = None
        if a.profile_link_id and a.profile_link and a.profile_link.patient:
            patient_id = a.profile_link.patient.id
            patient_uid = a.profile_link.patient.patient_uid
            patient_name = a.profile_link.patient.name
        doctor = db.query(Doctor).filter(Doctor.id == a.doctor_id).first() if a.doctor_id else None
        result.append({
            "id": a.id,
            "type": a.type.value,
            "requested_time": a.requested_time.isoformat(),
            "status": a.status.value,
            "notes": a.notes,
            "patient_id": patient_id,
            "patient_uid": patient_uid,
            "patient_name": patient_name,
            "doctor_id": a.doctor_id,
            "doctor_name": f"{doctor.title} {doctor.name}" if doctor else "Unassigned",
            "arrived_at": a.arrived_at.isoformat() if a.arrived_at else None,
            "payment_status": a.payment_status,
        })
    return {"count": len(result), "appointments": result}


@router.get("/upcoming")
def list_upcoming_bookings(
    doctor_id: int = Query(None),
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """Next 15 days of paid online bookings, hospital-wide — the piece
    reception previously had no visibility into at all (only ever saw
    today)."""
    if current_doctor.role.value not in _APPT_VIEW_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")
    today_start = datetime.combine(now_ist_naive().date(), datetime.min.time())
    window_end = today_start + timedelta(days=15)

    q = db.query(Appointment).filter(
        Appointment.hospital_id == current_doctor.hospital_id,
        Appointment.status.in_([AppointmentStatus.booked, AppointmentStatus.confirmed]),
        Appointment.requested_time >= today_start + timedelta(days=1),  # today itself stays on the Expected Today card
        Appointment.requested_time < window_end,
    )
    if doctor_id:
        q = q.filter(Appointment.doctor_id == doctor_id)

    appts = q.order_by(Appointment.requested_time).all()

    result = []
    for a in appts:
        patient_name = None
        patient_phone = None
        patient_age = None
        patient_gender = None
        if a.profile_link_id and a.profile_link and a.profile_link.patient:
            p = a.profile_link.patient
            patient_name = p.name
            patient_phone = p.phone
            patient_age = p.age
            patient_gender = p.gender
        elif a.new_patient_name:
            patient_name = a.new_patient_name
            patient_age = a.new_patient_age
            patient_gender = a.new_patient_gender
            patient_phone = a.account.phone if a.account else None
        doctor = db.query(Doctor).filter(Doctor.id == a.doctor_id).first() if a.doctor_id else None
        result.append({
            "id": a.id,
            "requested_time": a.requested_time.isoformat(),
            "patient_name": patient_name,
            "patient_phone": patient_phone,
            "patient_age": patient_age,
            "patient_gender": patient_gender,
            "doctor_id": a.doctor_id,
            "doctor_name": f"{doctor.title} {doctor.name}" if doctor else "Unassigned",
        })
    return {"count": len(result), "appointments": result}


@router.get("/pending-review")
def list_pending_review(
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """Two different reasons an appointment can sit here, distinguished by
    `reason` in the response: 'doctor_unavailable' (the original case — the
    doctor went unavailable after booking, needs accept/suggest/decline)
    and 'awaiting_payment' (a phone booking reception took via Book
    Appointment — status stays "booked"/unpaid until reception actually
    collects payment from the caller, at which point it moves to Expected
    Today). Keeping "awaiting_payment" rows at status=booked rather than
    reusing pending_review means the accept/suggest/decline endpoints below
    — which all gate on status == pending_review — can't accidentally act
    on a plain unpaid booking."""
    if current_doctor.role.value not in _STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")

    _expire_stale_pending_reviews(db, current_doctor.hospital_id)
    _expire_stale_awaiting_payment(db, current_doctor.hospital_id)

    needs_review = db.query(Appointment).filter(
        Appointment.hospital_id == current_doctor.hospital_id,
        Appointment.status == AppointmentStatus.pending_review,
    ).order_by(Appointment.review_deadline_at).all()

    awaiting_payment = db.query(Appointment).filter(
        Appointment.hospital_id == current_doctor.hospital_id,
        Appointment.status == AppointmentStatus.booked,
        Appointment.payment_status == "unpaid",
    ).order_by(Appointment.requested_time).all()

    hospital = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()

    def _resolve_fee(a, doctor):
        # a.fee_amount is whatever was set/locked at booking time — if it's
        # blank, fall back to the admin-set default the same way check-in
        # already does (doctor.consultation_fee, then the hospital-wide
        # default), so reception always has a sensible starting number
        # instead of an empty box.
        if a.fee_amount is not None:
            return a.fee_amount
        if doctor and doctor.consultation_fee is not None:
            return doctor.consultation_fee
        return hospital.default_consultation_fee if hospital else None

    result = []
    for a in needs_review:
        patient_name = a.new_patient_name
        if a.profile_link_id and a.profile_link and a.profile_link.patient:
            patient_name = a.profile_link.patient.name
        doctor = db.query(Doctor).filter(Doctor.id == a.doctor_id).first() if a.doctor_id else None
        result.append({
            "id": a.id,
            "reason": "doctor_unavailable",
            "patient_name": patient_name,
            "doctor_id": a.doctor_id,
            "doctor_name": f"{doctor.title} {doctor.name}" if doctor else "Unassigned",
            "requested_time": a.requested_time.isoformat(),
            "fee_amount": _resolve_fee(a, doctor),
            "review_deadline_at": a.review_deadline_at.isoformat() if a.review_deadline_at else None,
            "followup_sent": a.review_followup_sent_at is not None,
        })
    for a in awaiting_payment:
        patient_name = a.new_patient_name
        if a.profile_link_id and a.profile_link and a.profile_link.patient:
            patient_name = a.profile_link.patient.name
        doctor = db.query(Doctor).filter(Doctor.id == a.doctor_id).first() if a.doctor_id else None
        result.append({
            "id": a.id,
            "reason": "awaiting_payment",
            "hospital_id": a.hospital_id,
            "arrived_at": a.arrived_at.isoformat() if a.arrived_at else None,
            "late_unresolved": _late_unresolved(a),
            "grace_minutes": settings.PORTAL_PAYMENT_GRACE_MINUTES,
            "patient_name": patient_name,
            "doctor_id": a.doctor_id,
            "doctor_name": f"{doctor.title} {doctor.name}" if doctor else "Unassigned",
            "requested_time": a.requested_time.isoformat(),
            "fee_amount": _resolve_fee(a, doctor),
            "review_deadline_at": None,
            "followup_sent": False,
        })
    return {"count": len(result), "appointments": result}


@router.post("/{appointment_id}/mark-arrived")
def mark_arrived_by_staff(
    appointment_id: int,
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    if current_doctor.role.value not in _STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")

    appt = db.query(Appointment).filter(
        Appointment.id == appointment_id, Appointment.hospital_id == current_doctor.hospital_id
    ).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status not in (AppointmentStatus.confirmed, AppointmentStatus.completed):
        raise HTTPException(status_code=400, detail="This appointment isn't confirmed and ready for arrival")

    if not appt.arrived_at:
        appt.arrived_at = now_ist_naive()
        db.commit()

    if appt.profile_link_id and appt.profile_link and appt.profile_link.patient:
        convert_appointment_to_checkin(db, appt, appt.profile_link.patient)

    return {"message": "Marked arrived"}


@router.post("/{appointment_id}/accept")
def accept_appointment(
    appointment_id: int,
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    if current_doctor.role.value not in _STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")

    appt = db.query(Appointment).filter(
        Appointment.id == appointment_id, Appointment.hospital_id == current_doctor.hospital_id
    ).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status != AppointmentStatus.pending_review:
        raise HTTPException(status_code=400, detail="This appointment isn't awaiting review")

    if appt.requested_reschedule_slot_id:
        new_slot = db.query(DoctorSlot).filter(
            DoctorSlot.id == appt.requested_reschedule_slot_id, DoctorSlot.hospital_id == appt.hospital_id
        ).with_for_update().first()
        if not new_slot:
            raise HTTPException(status_code=404, detail="Requested slot no longer exists")
        if new_slot.booked_count >= new_slot.capacity:
            raise HTTPException(status_code=400, detail="That slot is already full")

        if appt.slot_id:
            old_slot = db.query(DoctorSlot).filter(DoctorSlot.id == appt.slot_id).with_for_update().first()
            if old_slot and old_slot.booked_count > 0:
                old_slot.booked_count -= 1

        new_slot.booked_count += 1
        appt.slot_id = new_slot.id
        appt.requested_time = _estimated_slot_datetime(new_slot, new_slot.booked_count)

        # Fee only changes when the reschedule switches doctors — the
        # self-serve mass-reschedule path (same doctor, different slot)
        # deliberately never touches this, and neither does this branch
        # when new_slot.doctor_id matches the original.
        if new_slot.doctor_id and new_slot.doctor_id != appt.doctor_id:
            from app.utils.portal_billing import current_doctor_fee
            old_fee = appt.fee_amount or 0.0
            new_fee = current_doctor_fee(db, new_slot.doctor_id)
            diff = round(new_fee - old_fee, 2)
            if diff < 0:
                from app.models.refund import Refund
                db.add(Refund(
                    patient_id=(appt.profile_link.patient.id if appt.profile_link_id and appt.profile_link and appt.profile_link.patient else None),
                    hospital_id=appt.hospital_id, source_type="appointment", source_id=appt.id,
                    amount=abs(diff), channel="online", status="pending",
                    reason=f"Rescheduled to a lower-fee doctor (Rs.{old_fee:.2f} -> Rs.{new_fee:.2f})",
                    processed_by=None,
                ))
            elif diff > 0:
                # No live payment gateway to charge this online mid-flow —
                # collected at check-in like any other OPD balance instead
                # (see convert_appointment_to_checkin).
                appt.reschedule_balance_due = (appt.reschedule_balance_due or 0.0) + diff
            appt.fee_amount = new_fee
            appt.doctor_id = new_slot.doctor_id

        appt.arrived_at = None  # fresh grace-window/arrival cycle applies to the new slot
        appt.no_show_detected_at = None
        appt.no_show_reason = None
        appt.no_show_reschedule_deadline = None
        appt.reschedule_kind = None
        appt.requested_reschedule_slot_id = None

    appt.status = AppointmentStatus.confirmed
    resolve_notification(db, appt.hospital_id, f"appointment_needs_review:{appt.id}")
    db.commit()
    log_action(
        db, current_doctor,
        action="appointment_review_accepted",
        target_type="appointment",
        target_id=appt.id,
        details=f"pending_review -> confirmed, doctor_id {appt.doctor_id}, time {appt.requested_time.isoformat()}, fee Rs.{(appt.fee_amount or 0):.2f}",
    )
    return {"message": "Appointment accepted"}


@router.post("/{appointment_id}/decline")
def decline_appointment(
    appointment_id: int,
    body: DeclineAppointmentIn,
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    if current_doctor.role.value not in _STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")

    appt = db.query(Appointment).filter(
        Appointment.id == appointment_id, Appointment.hospital_id == current_doctor.hospital_id
    ).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status != AppointmentStatus.pending_review:
        raise HTTPException(status_code=400, detail="This appointment isn't awaiting review")

    if appt.reschedule_kind == "no_show":
        # Being late was the patient's responsibility — no refund for
        # declining their proposed slot. They can still try again with a
        # different slot as long as they're within the 72hr window.
        appt.reschedule_kind = None
        appt.requested_reschedule_slot_id = None
        appt.review_deadline_at = None
        appt.review_followup_sent_at = None
        appt.status = AppointmentStatus.confirmed
        resolve_notification(db, appt.hospital_id, f"appointment_needs_review:{appt.id}")
        db.commit()
        log_action(
            db, current_doctor,
            action="appointment_reschedule_declined",
            target_type="appointment",
            target_id=appt.id,
            details="no-show reschedule request declined, no refund",
        )
        return {"message": "Reschedule request declined — patient can request a different slot within their 72hr window"}

    reason = f"Declined by hospital{': ' + body.reason if body.reason else ''}"
    create_patient_cancellation_refund(db, appt, reason=reason, percent=100)
    if appt.slot_id:
        slot = db.query(DoctorSlot).filter(DoctorSlot.id == appt.slot_id).with_for_update().first()
        if slot and slot.booked_count > 0:
            slot.booked_count -= 1

    appt.status = AppointmentStatus.cancelled
    resolve_notification(db, appt.hospital_id, f"appointment_needs_review:{appt.id}")
    db.commit()
    log_action(
        db, current_doctor,
        action="appointment_declined_refunded",
        target_type="appointment",
        target_id=appt.id,
        details=f"pending_review -> cancelled, full refund Rs.{(appt.fee_amount or 0):.2f}. {reason}"[:1500],
    )
    return {"message": "Appointment declined and fully refunded"}


@router.post("/{appointment_id}/suggest")
def suggest_new_slot(
    appointment_id: int,
    body: SuggestAppointmentIn,
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    if current_doctor.role.value not in _STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")
    if not body.new_slot_id and not body.new_doctor_id:
        raise HTTPException(status_code=400, detail="Provide a new slot and/or doctor to suggest")

    appt = db.query(Appointment).filter(
        Appointment.id == appointment_id, Appointment.hospital_id == current_doctor.hospital_id
    ).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status != AppointmentStatus.pending_review:
        raise HTTPException(status_code=400, detail="This appointment isn't awaiting review")

    old_fee = appt.fee_amount or 0
    old_slot_id = appt.slot_id
    old_doctor_id = appt.doctor_id

    if body.new_doctor_id:
        from app.models.doctor import UserRole
        _nd = db.query(Doctor).filter(
            Doctor.id == body.new_doctor_id,
            Doctor.hospital_id == current_doctor.hospital_id,
            Doctor.is_active == True,  # noqa: E712
            Doctor.role == UserRole.doctor,
        ).first()
        if not _nd:
            raise HTTPException(status_code=400, detail="Selected doctor is not available in this hospital")
        if body.new_doctor_id != appt.doctor_id and not body.new_slot_id:
            raise HTTPException(status_code=400, detail="Pick a slot with the new doctor")

    if body.new_slot_id:
        new_slot = db.query(DoctorSlot).filter(
            DoctorSlot.id == body.new_slot_id, DoctorSlot.hospital_id == current_doctor.hospital_id
        ).with_for_update().first()
        if not new_slot:
            raise HTTPException(status_code=404, detail="Slot not found")
        if new_slot.booked_count >= new_slot.capacity:
            raise HTTPException(status_code=400, detail="That slot is already full")
        if body.new_doctor_id and new_slot.doctor_id != body.new_doctor_id:
            raise HTTPException(status_code=400, detail="That slot belongs to a different doctor")
        _s_start = datetime.combine(new_slot.slot_date, datetime.strptime(new_slot.slot_time, "%H:%M").time())
        if _s_start + timedelta(minutes=new_slot.window_minutes or 0) <= now_ist_naive():
            raise HTTPException(status_code=400, detail="That slot has already passed")

        if old_slot_id:
            old_slot = db.query(DoctorSlot).filter(DoctorSlot.id == old_slot_id).with_for_update().first()
            if old_slot and old_slot.booked_count > 0:
                old_slot.booked_count -= 1

        new_slot.booked_count += 1
        appt.slot_id = new_slot.id
        appt.doctor_id = body.new_doctor_id or new_slot.doctor_id
        appt.requested_time = _estimated_slot_datetime(new_slot, new_slot.booked_count)
    elif body.new_doctor_id:
        appt.doctor_id = body.new_doctor_id

    new_fee = current_doctor_fee(db, appt.doctor_id)
    appt.fee_amount = new_fee
    fee_delta = round(new_fee - old_fee, 2)

    if fee_delta <= 0:
        if fee_delta < 0:
            create_patient_cancellation_refund(
                db, appt, reason="Suggested change — lower fee", fixed_amount=abs(fee_delta),
            )
        appt.status = AppointmentStatus.confirmed
    else:
        # New doctor/slot costs more: the original payment stays credited and the
        # difference is collected at check-in (same logic as accept above).
        appt.reschedule_balance_due = (appt.reschedule_balance_due or 0.0) + fee_delta
        appt.status = AppointmentStatus.confirmed

    appt.arrived_at = None
    appt.no_show_detected_at = None
    appt.no_show_reason = None
    appt.no_show_reschedule_deadline = None
    appt.reschedule_kind = None
    appt.requested_reschedule_slot_id = None
    resolve_notification(db, appt.hospital_id, f"appointment_needs_review:{appt.id}")
    db.commit()
    log_action(
        db, current_doctor,
        action="appointment_change_suggested",
        target_type="appointment",
        target_id=appt.id,
        details=f"doctor {old_doctor_id} -> {appt.doctor_id}, fee Rs.{old_fee:.2f} -> Rs.{new_fee:.2f}, balance due Rs.{(appt.reschedule_balance_due or 0):.2f}",
    )
    return {"message": "Suggestion applied", "fee_delta": fee_delta, "status": appt.status.value}