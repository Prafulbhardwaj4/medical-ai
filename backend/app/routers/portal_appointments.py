from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.models.portal import Appointment, AppointmentStatus, AppointmentType, PatientAccount
from app.models.doctor_slot import DoctorSlot
from app.models.doctor import Doctor
from app.models.hospital import Hospital
from app.schemas.portal import (
    BookAppointmentIn, AppointmentOut, NoShowReasonIn, RequestRescheduleIn,
    FamilyBookingRequestIn, FamilyBookingConfirmIn, ReportIssueIn,
)
from app.utils.portal_auth import get_current_patient_account
from app.utils.timezone import now_ist_naive
from app.utils.phone import normalize_phone

router = APIRouter(prefix="/portal/appointments", tags=["portal-appointments"])


def _to_out(a: Appointment, db: Session) -> AppointmentOut:
    hospital = db.query(Hospital).filter(Hospital.id == a.hospital_id).first()
    doctor = db.query(Doctor).filter(Doctor.id == a.doctor_id).first() if a.doctor_id else None
    patient_name = a.new_patient_name
    if a.profile_link_id:
        from app.models.portal import PatientProfileLink
        link = db.query(PatientProfileLink).filter(PatientProfileLink.id == a.profile_link_id).first()
        if link and link.patient:
            patient_name = link.patient.name
    return AppointmentOut(
        id=a.id, hospital_id=a.hospital_id, hospital_name=hospital.name if hospital else None,
        doctor_id=a.doctor_id, doctor_name=f"{doctor.title} {doctor.name}" if doctor else None,
        patient_name=patient_name,
        type=a.type.value, requested_time=a.requested_time, status=a.status.value,
        payment_status=a.payment_status, notes=a.notes, address=a.address,
        fee_amount=a.fee_amount, arrived_at=a.arrived_at,
        needs_no_show_response=a.no_show_detected_at is not None and a.no_show_reason is None,
        no_show_reschedule_deadline=a.no_show_reschedule_deadline,
        mass_reschedule_notice=a.mass_reschedule_notice,
    )


def _release_abandoned_holds(db: Session, slot: DoctorSlot) -> None:
    """Abandoned (never-paid) holds don't get to sit on a slot forever. There's
    no background scheduler in this codebase yet, so this is a lazy expiry
    sweep: anyone touching this slot (booking, checking capacity, paying)
    triggers it, and any unpaid hold past the grace window gets released and
    the slot count freed up for someone else. Caller must already hold the
    row lock on `slot` before calling this."""
    cutoff = now_ist_naive() - timedelta(minutes=settings.PORTAL_BOOKING_HOLD_MINUTES)
    stale = db.query(Appointment).filter(
        Appointment.slot_id == slot.id,
        Appointment.status == AppointmentStatus.booked,
        Appointment.payment_status == "unpaid",
        Appointment.created_at < cutoff,
    ).all()
    for a in stale:
        a.status = AppointmentStatus.cancelled
        a.payment_status = "expired"
        if slot.booked_count > 0:
            slot.booked_count -= 1
    if stale:
        db.flush()


ACTIVE_APPOINTMENT_STATUSES = (AppointmentStatus.booked, AppointmentStatus.pending_review, AppointmentStatus.confirmed)


def _check_no_duplicate_active_booking(db: Session, account: PatientAccount, profile_link_id, new_patient_name, doctor_id: int) -> None:
    """One active booking per doctor per patient (Phase 2 item 6). Identity is
    the profile_link_id when this account already has a real hospital record
    for this person; for a genuinely new patient with no record yet, identity
    is proxied by this account + the name they're booking under, so two
    different family members typed under different names don't collide, but
    the same person can't stack two bookings with the same doctor."""
    query = db.query(Appointment).filter(
        Appointment.doctor_id == doctor_id,
        Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
    )
    if profile_link_id:
        query = query.filter(Appointment.profile_link_id == profile_link_id)
    else:
        query = query.filter(
            Appointment.account_id == account.id,
            Appointment.profile_link_id.is_(None),
            Appointment.new_patient_name == (new_patient_name or "").strip(),
        )
    if query.first():
        raise HTTPException(status_code=400, detail="You already have an active appointment with this doctor. Cancel or complete it before booking another.")


@router.post("", response_model=AppointmentOut)
def book_appointment(
    body: BookAppointmentIn,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    if body.profile_link_id:
        owned = any(p.id == body.profile_link_id for p in account.profiles)
        if not owned:
            raise HTTPException(status_code=403, detail="This profile does not belong to your account")
    else:
        if not (body.new_patient_name or "").strip():
            raise HTTPException(status_code=400, detail="Please enter the patient's name — this hospital hasn't seen this account before")

    hospital = db.query(Hospital).filter(Hospital.id == body.hospital_id, Hospital.is_active == True).first()  # noqa: E712
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    try:
        appt_type = AppointmentType(body.type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid appointment type")

    doctor_id = body.doctor_id
    requested_time = body.requested_time
    slot_id = None

    if appt_type == AppointmentType.scheduled:
        if not body.slot_id:
            raise HTTPException(status_code=400, detail="Select a time slot to book an appointment")

        # Row-level lock: holds this slot row for the rest of the request so
        # two concurrent bookings for the last opening can't both pass the
        # capacity check below and overbook it.
        slot = db.query(DoctorSlot).filter(
            DoctorSlot.id == body.slot_id, DoctorSlot.hospital_id == body.hospital_id
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

        _check_no_duplicate_active_booking(db, account, body.profile_link_id, body.new_patient_name, slot.doctor_id)

        slot.booked_count += 1
        doctor_id = slot.doctor_id
        requested_time = datetime.combine(slot.slot_date, datetime.strptime(slot.slot_time, "%H:%M").time())
        slot_id = slot.id
    else:
        requested_time = now_ist_naive()
        if body.doctor_id:
            _check_no_duplicate_active_booking(db, account, body.profile_link_id, body.new_patient_name, body.doctor_id)

    if body.address_id:
        from app.models.portal import PatientAddress
        saved = db.query(PatientAddress).filter(PatientAddress.id == body.address_id, PatientAddress.account_id == account.id).first()
        if not saved:
            raise HTTPException(status_code=404, detail="Saved address not found")
        resolved_address = saved.address
    elif body.use_saved_address:
        resolved_address = account.address
    else:
        resolved_address = (body.custom_address or "").strip() or None

    appt = Appointment(
        account_id=account.id,
        profile_link_id=body.profile_link_id,
        hospital_id=body.hospital_id,
        doctor_id=doctor_id,
        slot_id=slot_id,
        type=appt_type,
        requested_time=requested_time,
        notes=body.notes,
        status=AppointmentStatus.booked,
        payment_status="unpaid",
        address=resolved_address,
        new_patient_name=(body.new_patient_name or "").strip() or None if not body.profile_link_id else None,
        new_patient_gender=body.new_patient_gender if not body.profile_link_id else None,
        new_patient_age=body.new_patient_age if not body.profile_link_id else None,
        new_patient_blood_group=body.new_patient_blood_group if not body.profile_link_id else None,
    )
    db.add(appt)
    db.commit()
    db.refresh(appt)

    # If this booking is for an existing hospital record that has no address
    # on file yet, backfill it — never overwrites an address reception already has.
    if body.profile_link_id and resolved_address:
        from app.models.portal import PatientProfileLink
        link = db.query(PatientProfileLink).filter(PatientProfileLink.id == body.profile_link_id).first()
        if link and link.patient and not link.patient.address:
            link.patient.address = resolved_address
            db.commit()

    # Genuinely new patient at this hospital — alert reception with a link to a pre-filled Add Patient flow.
    if not body.profile_link_id:
        from app.models.notification import Notification
        db.add(Notification(
            hospital_id=body.hospital_id,
            source_key=f"new_portal_patient:{appt.id}",
            type="new_portal_patient",
            severity="info",
            title="New Patient Booked Online",
            message=f"{appt.new_patient_name} booked an appointment via the portal and isn't in your patient list yet.",
            link_type="portal_appointment",
            link_id=appt.id,
        ))
        db.commit()

    return _to_out(appt, db)


@router.get("", response_model=list[AppointmentOut])
def list_my_appointments(
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    from app.utils.portal_noshow import detect_no_shows
    hospital_ids = {a.hospital_id for a in account.appointments}
    for hid in hospital_ids:
        detect_no_shows(db, hid)

    appts = sorted(account.appointments, key=lambda x: x.requested_time, reverse=True)
    return [_to_out(a, db) for a in appts]


@router.post("/{appointment_id}/mark-paid", response_model=AppointmentOut)
def mark_paid(
    appointment_id: int,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    """Static placeholder for a real payment gateway. Only once an
    appointment is marked paid does it show up in the hospital's queue /
    'Expected Today' view or get auto-matched at check-in."""
    appt = next((a for a in account.appointments if a.id == appointment_id), None)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status == AppointmentStatus.cancelled:
        raise HTTPException(status_code=400, detail="Cannot pay for a cancelled appointment")

    if appt.slot_id and appt.status == AppointmentStatus.booked and appt.payment_status == "unpaid":
        cutoff = now_ist_naive() - timedelta(minutes=settings.PORTAL_BOOKING_HOLD_MINUTES)
        if appt.created_at < cutoff:
            slot = db.query(DoctorSlot).filter(DoctorSlot.id == appt.slot_id).with_for_update().first()
            if slot and slot.booked_count > 0:
                slot.booked_count -= 1
            appt.status = AppointmentStatus.cancelled
            appt.payment_status = "expired"
            db.commit()
            db.refresh(appt)
            raise HTTPException(status_code=410, detail="This booking hold expired before payment was completed. Please book again.")

    from app.utils.portal_billing import current_doctor_fee
    if appt.doctor_id:
        appt.fee_amount = current_doctor_fee(db, appt.doctor_id)

    appt.payment_status = "paid"

    # Auto-approve by default — booking-time checks (doctor availability,
    # slot capacity) already prevent most conflicts. The one real edge case
    # left is the doctor going unavailable *after* booking but *before*
    # payment, which only shows up now.
    needs_review = False
    if appt.doctor_id:
        from app.models.doctor_availability import DoctorUnavailability
        needs_review = db.query(DoctorUnavailability).filter(
            DoctorUnavailability.doctor_id == appt.doctor_id,
            DoctorUnavailability.date == appt.requested_time.date(),
        ).first() is not None

    if needs_review:
        appt.status = AppointmentStatus.pending_review
        appt.review_deadline_at = now_ist_naive() + timedelta(minutes=settings.PORTAL_REVIEW_RESPONSE_MINUTES)
        from app.models.notification import Notification
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
    return _to_out(appt, db)


@router.post("/{appointment_id}/no-show-reason", response_model=AppointmentOut)
def submit_no_show_reason(
    appointment_id: int,
    body: NoShowReasonIn,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    if body.reason not in ("hospital_delay", "patient_no_show"):
        raise HTTPException(status_code=400, detail="Invalid reason")

    appt = next((a for a in account.appointments if a.id == appointment_id), None)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if not appt.no_show_detected_at or appt.no_show_reason:
        raise HTTPException(status_code=400, detail="No pending no-show response needed for this appointment")

    appt.no_show_reason = body.reason
    appt.no_show_reschedule_deadline = appt.requested_time + timedelta(hours=72)

    if body.reason == "hospital_delay":
        from app.models.notification import Notification
        db.add(Notification(
            hospital_id=appt.hospital_id,
            source_key=f"appointment_hospital_delay:{appt.id}",
            type="appointment_hospital_delay",
            severity="critical",
            title="Patient reports hospital-side delay",
            message=f"Appointment #{appt.id} — patient reports they weren't seen and believes it's a hospital/scheduling issue.",
            link_type="portal_appointment", link_id=appt.id,
        ))

    db.commit()
    db.refresh(appt)
    return _to_out(appt, db)


@router.post("/report-issue")
def report_issue(
    body: ReportIssueIn,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    """Lightweight 'something went wrong' report for a dropped screen during
    booking/payment or check-in — always visible, always succeeds (this
    exists specifically to work when the normal flow just broke), routes to
    hospital staff at top priority. Deliberately not a support-ticket
    system — just a Notification, same as every other staff alert in this
    app. appointment_id is best-effort: it may not resolve to anything if
    the drop happened before the booking record was even created, and that's
    fine — the report still goes through."""
    if body.context not in ("booking_payment", "checkin", "other"):
        raise HTTPException(status_code=400, detail="Invalid context")

    from app.models.hospital import Hospital
    hospital = db.query(Hospital).filter(Hospital.id == body.hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    appt = None
    if body.appointment_id:
        appt = next((a for a in account.appointments if a.id == body.appointment_id), None)

    from app.models.notification import Notification
    context_label = {"booking_payment": "booking/payment", "checkin": "arrival/check-in", "other": "portal"}[body.context]
    db.add(Notification(
        hospital_id=hospital.id,
        source_key=f"portal_issue_reported:{account.id}:{now_ist_naive().isoformat()}",
        type="portal_issue_reported",
        severity="critical",
        title=f"Patient reports something went wrong ({context_label})",
        message=f"{account.phone} reported an issue during {context_label}" + (f" on appointment #{appt.id}" if appt else " — no specific appointment resolved, may have dropped before booking completed") + (f". Note: {body.message.strip()}" if body.message and body.message.strip() else "") + ". Payment success is always the source of truth server-side — check payment_status before assuming anything was lost.",
        link_type="portal_appointment" if appt else None, link_id=appt.id if appt else None,
    ))
    db.commit()
    return {"message": "Reported — hospital staff have been notified and will follow up. If a payment went through, it's already recorded on our side regardless of what your screen showed."}


@router.post("/{appointment_id}/arrived", response_model=AppointmentOut)
def mark_arrived(
    appointment_id: int,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    appt = next((a for a in account.appointments if a.id == appointment_id), None)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status != AppointmentStatus.confirmed:
        raise HTTPException(status_code=400, detail="This appointment isn't confirmed and ready for arrival")
    if appt.requested_time.date() != now_ist_naive().date():
        raise HTTPException(status_code=400, detail="You can only mark arrival on the day of your appointment")

    if not appt.arrived_at:
        appt.arrived_at = now_ist_naive()
        db.commit()

    if appt.profile_link_id and appt.profile_link and appt.profile_link.patient:
        from app.utils.portal_checkin import convert_appointment_to_checkin
        convert_appointment_to_checkin(db, appt, appt.profile_link.patient)
        db.refresh(appt)

    return _to_out(appt, db)


@router.post("/{appointment_id}/request-reschedule", response_model=AppointmentOut)
def request_reschedule(
    appointment_id: int,
    body: RequestRescheduleIn,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    appt = next((a for a in account.appointments if a.id == appointment_id), None)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status != AppointmentStatus.confirmed:
        raise HTTPException(status_code=400, detail="Reschedule isn't available for this appointment right now")

    now = now_ist_naive()
    if appt.no_show_reason and appt.no_show_reschedule_deadline and now <= appt.no_show_reschedule_deadline:
        kind = "no_show"
    elif not appt.no_show_detected_at and appt.requested_time.date() == now.date() and now < appt.requested_time:
        kind = "same_day"
    else:
        raise HTTPException(status_code=400, detail="Reschedule isn't available for this appointment right now")

    appt.reschedule_kind = kind
    appt.requested_reschedule_slot_id = body.new_slot_id
    appt.status = AppointmentStatus.pending_review
    appt.review_deadline_at = now + timedelta(minutes=settings.PORTAL_REVIEW_RESPONSE_MINUTES)
    appt.review_followup_sent_at = None

    from app.models.notification import Notification
    db.add(Notification(
        hospital_id=appt.hospital_id,
        source_key=f"appointment_reschedule_requested:{appt.id}",
        type="appointment_reschedule_requested",
        severity="warning",
        title="Reschedule requested",
        message=f"Appointment #{appt.id} — patient requested a {'no-show' if kind == 'no_show' else 'same-day'} reschedule. Accept, suggest a change, or decline.",
        link_type="portal_appointment", link_id=appt.id,
    ))

    db.commit()
    db.refresh(appt)
    return _to_out(appt, db)


@router.post("/family-booking-request")
def request_family_booking(
    body: FamilyBookingRequestIn,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    """Family member has their own separate account — no duplicate profile
    gets created. Instead of an (undeliverable, no-WhatsApp) OTP, the target
    account sees and confirms this the next time they open their own
    portal, same pattern as the pending-confirmation profile flow."""
    from app.models.portal import CrossBookingRequest

    phone = normalize_phone(body.other_account_phone)
    if phone == account.phone:
        raise HTTPException(status_code=400, detail="That's your own account — book under one of your existing profiles instead")

    target = db.query(PatientAccount).filter(PatientAccount.phone == phone).first()
    if not target:
        raise HTTPException(status_code=404, detail="No portal account found with that phone number")

    hospital = db.query(Hospital).filter(Hospital.id == body.hospital_id, Hospital.is_active == True).first()  # noqa: E712
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    req = CrossBookingRequest(
        requesting_account_id=account.id,
        target_account_id=target.id,
        hospital_id=body.hospital_id,
        doctor_id=body.doctor_id,
        slot_id=body.slot_id,
        type=body.type,
        notes=body.notes,
        address=body.custom_address,
        status="pending",
    )
    db.add(req)
    db.commit()
    return {"message": "Sent — they'll see this the next time they open their portal"}


@router.get("/family-booking-requests")
def list_family_booking_requests(
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    """Requests where I'M the target — someone wants to book an appointment
    for me using my own account, and I need to confirm it's really me."""
    from app.models.portal import CrossBookingRequest

    rows = db.query(CrossBookingRequest).filter(
        CrossBookingRequest.target_account_id == account.id,
        CrossBookingRequest.status == "pending",
    ).order_by(CrossBookingRequest.created_at.desc()).all()

    result = []
    for r in rows:
        requester = db.query(PatientAccount).filter(PatientAccount.id == r.requesting_account_id).first()
        hospital = db.query(Hospital).filter(Hospital.id == r.hospital_id).first()
        doctor = db.query(Doctor).filter(Doctor.id == r.doctor_id).first() if r.doctor_id else None
        result.append({
            "id": r.id,
            "requester_phone": requester.phone if requester else "Unknown",
            "hospital_name": hospital.name if hospital else "Unknown hospital",
            "doctor_name": f"{doctor.title} {doctor.name}" if doctor else None,
            "type": r.type,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return result


@router.post("/family-booking-requests/{request_id}/reject")
def reject_family_booking_request(
    request_id: int,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    from app.models.portal import CrossBookingRequest

    req = db.query(CrossBookingRequest).filter(
        CrossBookingRequest.id == request_id, CrossBookingRequest.target_account_id == account.id
    ).first()
    if not req or req.status != "pending":
        raise HTTPException(status_code=404, detail="Request not found")
    req.status = "rejected"
    db.commit()
    return {"message": "Rejected"}


@router.post("/family-booking-requests/{request_id}/confirm", response_model=AppointmentOut)
def confirm_family_booking_request(
    request_id: int,
    body: FamilyBookingConfirmIn,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    """Confirming links the booking to MY existing account/profile instead
    of a new duplicate profile. Slot capacity and doctor availability are
    checked here, not at request time, so a pending request never holds a
    slot hostage while waiting on the other person."""
    from app.models.portal import CrossBookingRequest, PatientProfileLink

    req = db.query(CrossBookingRequest).filter(
        CrossBookingRequest.id == request_id, CrossBookingRequest.target_account_id == account.id
    ).first()
    if not req or req.status != "pending":
        raise HTTPException(status_code=404, detail="Request not found")

    self_link = next(
        (p for p in account.profiles if p.relation == "self" and p.patient and p.patient.hospital_id == req.hospital_id),
        None,
    )
    profile_link_id = self_link.id if self_link else None
    if not profile_link_id and not (body.new_patient_name or "").strip():
        raise HTTPException(status_code=400, detail="Please enter your name — this hospital hasn't seen your account before")

    doctor_id = req.doctor_id
    requested_time = now_ist_naive()
    slot_id = None

    if req.type == "scheduled":
        if not req.slot_id:
            raise HTTPException(status_code=400, detail="No slot was specified on this request")
        slot = db.query(DoctorSlot).filter(DoctorSlot.id == req.slot_id, DoctorSlot.hospital_id == req.hospital_id).with_for_update().first()
        if not slot:
            raise HTTPException(status_code=404, detail="That slot no longer exists")
        _release_abandoned_holds(db, slot)
        if slot.booked_count >= slot.capacity:
            raise HTTPException(status_code=400, detail="This slot has since filled up. Ask them to pick another.")
        from app.models.doctor_availability import DoctorUnavailability
        if db.query(DoctorUnavailability).filter(
            DoctorUnavailability.doctor_id == slot.doctor_id, DoctorUnavailability.date == slot.slot_date
        ).first():
            raise HTTPException(status_code=400, detail="This doctor is unavailable on this date now. Ask them to pick another.")
        _check_no_duplicate_active_booking(db, account, profile_link_id, body.new_patient_name, slot.doctor_id)
        slot.booked_count += 1
        doctor_id = slot.doctor_id
        requested_time = datetime.combine(slot.slot_date, datetime.strptime(slot.slot_time, "%H:%M").time())
        slot_id = slot.id
    elif req.doctor_id:
        _check_no_duplicate_active_booking(db, account, profile_link_id, body.new_patient_name, req.doctor_id)

    appt = Appointment(
        account_id=account.id,
        profile_link_id=profile_link_id,
        hospital_id=req.hospital_id,
        doctor_id=doctor_id,
        slot_id=slot_id,
        type=AppointmentType(req.type),
        requested_time=requested_time,
        notes=req.notes,
        status=AppointmentStatus.booked,
        payment_status="unpaid",
        address=req.address,
        new_patient_name=(body.new_patient_name or "").strip() or None if not profile_link_id else None,
        new_patient_gender=body.new_patient_gender if not profile_link_id else None,
        new_patient_age=body.new_patient_age if not profile_link_id else None,
        requested_by_account_id=req.requesting_account_id,
    )
    db.add(appt)
    req.status = "confirmed"
    db.commit()
    db.refresh(appt)
    return _to_out(appt, db)


@router.post("/{appointment_id}/mass-reschedule", response_model=AppointmentOut)
def self_serve_mass_reschedule(
    appointment_id: int,
    body: RequestRescheduleIn,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    appt = next((a for a in account.appointments if a.id == appointment_id), None)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if not appt.mass_reschedule_notice:
        raise HTTPException(status_code=400, detail="No reschedule notice on this appointment")

    new_slot = db.query(DoctorSlot).filter(DoctorSlot.id == body.new_slot_id).with_for_update().first()
    if not new_slot:
        raise HTTPException(status_code=404, detail="Slot not found")
    if new_slot.doctor_id != appt.doctor_id:
        raise HTTPException(status_code=400, detail="Please pick a slot with the same doctor")
    if new_slot.booked_count >= new_slot.capacity:
        raise HTTPException(status_code=400, detail="That slot is already full")

    if appt.slot_id:
        old_slot = db.query(DoctorSlot).filter(DoctorSlot.id == appt.slot_id).with_for_update().first()
        if old_slot and old_slot.booked_count > 0:
            old_slot.booked_count -= 1

    new_slot.booked_count += 1
    appt.slot_id = new_slot.id
    appt.requested_time = datetime.combine(new_slot.slot_date, datetime.strptime(new_slot.slot_time, "%H:%M").time())
    # Already-paid fee carries over automatically — no refund-then-repay cycle.
    appt.mass_reschedule_notice = False
    appt.arrived_at = None
    appt.no_show_detected_at = None
    appt.no_show_reason = None
    appt.no_show_reschedule_deadline = None

    db.commit()
    db.refresh(appt)
    return _to_out(appt, db)


@router.post("/{appointment_id}/cancel", response_model=AppointmentOut)
def cancel_appointment(
    appointment_id: int,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    appt = next((a for a in account.appointments if a.id == appointment_id), None)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status in (AppointmentStatus.completed, AppointmentStatus.cancelled):
        raise HTTPException(status_code=400, detail=f"Cannot cancel a {appt.status.value} appointment")

    if appt.payment_status == "paid":
        now = now_ist_naive()
        hours_since_booking = (now - appt.created_at).total_seconds() / 3600
        hours_to_consultation = (appt.requested_time - now).total_seconds() / 3600

        if hours_to_consultation < settings.PORTAL_CANCEL_BLOCK_HOURS_BEFORE_CONSULT:
            raise HTTPException(
                status_code=400,
                detail=f"Cancellation isn't allowed within {settings.PORTAL_CANCEL_BLOCK_HOURS_BEFORE_CONSULT} hours of your consultation time.",
            )

        percent = (
            100 if hours_since_booking <= settings.PORTAL_CANCEL_FULL_REFUND_HOURS
            else settings.PORTAL_CANCEL_PARTIAL_REFUND_PERCENT
        )
        from app.utils.portal_billing import create_patient_cancellation_refund
        create_patient_cancellation_refund(db, appt, reason="Patient-initiated cancellation", percent=percent)

    if appt.slot_id:
        slot = db.query(DoctorSlot).filter(DoctorSlot.id == appt.slot_id).with_for_update().first()
        if slot and slot.booked_count > 0:
            slot.booked_count -= 1

    appt.status = AppointmentStatus.cancelled
    db.commit()
    db.refresh(appt)
    return _to_out(appt, db)