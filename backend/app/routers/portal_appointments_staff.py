from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.models.portal import Appointment, AppointmentStatus
from app.models.doctor import Doctor
from app.models.doctor_slot import DoctorSlot
from app.models.notification import Notification
from app.schemas.portal import DeclineAppointmentIn, SuggestAppointmentIn
from app.utils.auth import get_current_doctor
from app.utils.timezone import now_ist_naive
from app.utils.portal_billing import current_doctor_fee, create_patient_cancellation_refund
from app.utils.portal_checkin import convert_appointment_to_checkin

router = APIRouter(prefix="/portal-appointments-staff", tags=["portal-appointments-staff"])

_STAFF_ROLES = ["admin", "sub_admin", "receptionist"]


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


@router.get("/today")
def list_expected_today(
    doctor_id: int = Query(None),
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    from app.utils.portal_checkin import sweep_todays_online_checkins
    from app.utils.portal_noshow import detect_no_shows
    sweep_todays_online_checkins(db, current_doctor.hospital_id)
    detect_no_shows(db, current_doctor.hospital_id)

    today_start = datetime.combine(now_ist_naive().date(), datetime.min.time())
    today_end = today_start + timedelta(days=1)

    q = db.query(Appointment).filter(
        Appointment.hospital_id == current_doctor.hospital_id,
        Appointment.status.in_([AppointmentStatus.booked, AppointmentStatus.confirmed]),
        Appointment.payment_status == "paid",  # only paid appointments show up in the queue view
        Appointment.requested_time >= today_start,
        Appointment.requested_time < today_end,
    )
    if doctor_id:
        q = q.filter(Appointment.doctor_id == doctor_id)

    appts = q.order_by(Appointment.requested_time).all()

    result = []
    for a in appts:
        patient_name = None
        if a.profile_link_id and a.profile_link and a.profile_link.patient:
            patient_name = a.profile_link.patient.name
        doctor = db.query(Doctor).filter(Doctor.id == a.doctor_id).first() if a.doctor_id else None
        result.append({
            "id": a.id,
            "type": a.type.value,
            "requested_time": a.requested_time.isoformat(),
            "status": a.status.value,
            "notes": a.notes,
            "patient_name": patient_name,
            "doctor_id": a.doctor_id,
            "doctor_name": f"{doctor.title} {doctor.name}" if doctor else "Unassigned",
            "arrived_at": a.arrived_at.isoformat() if a.arrived_at else None,
        })
    return {"count": len(result), "appointments": result}


@router.get("/pending-review")
def list_pending_review(
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    if current_doctor.role.value not in _STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")

    _expire_stale_pending_reviews(db, current_doctor.hospital_id)

    appts = db.query(Appointment).filter(
        Appointment.hospital_id == current_doctor.hospital_id,
        Appointment.status == AppointmentStatus.pending_review,
    ).order_by(Appointment.review_deadline_at).all()

    result = []
    for a in appts:
        patient_name = a.new_patient_name
        if a.profile_link_id and a.profile_link and a.profile_link.patient:
            patient_name = a.profile_link.patient.name
        doctor = db.query(Doctor).filter(Doctor.id == a.doctor_id).first() if a.doctor_id else None
        result.append({
            "id": a.id,
            "patient_name": patient_name,
            "doctor_id": a.doctor_id,
            "doctor_name": f"{doctor.title} {doctor.name}" if doctor else "Unassigned",
            "requested_time": a.requested_time.isoformat(),
            "fee_amount": a.fee_amount,
            "review_deadline_at": a.review_deadline_at.isoformat() if a.review_deadline_at else None,
            "followup_sent": a.review_followup_sent_at is not None,
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
    if appt.status != AppointmentStatus.confirmed:
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
        new_slot = db.query(DoctorSlot).filter(DoctorSlot.id == appt.requested_reschedule_slot_id).with_for_update().first()
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
        appt.requested_time = datetime.combine(new_slot.slot_date, datetime.strptime(new_slot.slot_time, "%H:%M").time())

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
    db.commit()
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
        db.commit()
        return {"message": "Reschedule request declined — patient can request a different slot within their 72hr window"}

    reason = f"Declined by hospital{': ' + body.reason if body.reason else ''}"
    create_patient_cancellation_refund(db, appt, reason=reason, percent=100)
    if appt.slot_id:
        slot = db.query(DoctorSlot).filter(DoctorSlot.id == appt.slot_id).with_for_update().first()
        if slot and slot.booked_count > 0:
            slot.booked_count -= 1

    appt.status = AppointmentStatus.cancelled
    db.commit()
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

    if body.new_slot_id:
        new_slot = db.query(DoctorSlot).filter(
            DoctorSlot.id == body.new_slot_id, DoctorSlot.hospital_id == current_doctor.hospital_id
        ).with_for_update().first()
        if not new_slot:
            raise HTTPException(status_code=404, detail="Slot not found")
        if new_slot.booked_count >= new_slot.capacity:
            raise HTTPException(status_code=400, detail="That slot is already full")

        if old_slot_id:
            old_slot = db.query(DoctorSlot).filter(DoctorSlot.id == old_slot_id).with_for_update().first()
            if old_slot and old_slot.booked_count > 0:
                old_slot.booked_count -= 1

        new_slot.booked_count += 1
        appt.slot_id = new_slot.id
        appt.doctor_id = body.new_doctor_id or new_slot.doctor_id
        appt.requested_time = datetime.combine(new_slot.slot_date, datetime.strptime(new_slot.slot_time, "%H:%M").time())
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
        # New doctor/slot costs more — patient pays the difference before
        # this confirms. Reuses the existing mark-paid placeholder flow
        # rather than inventing a separate partial-payment mechanism.
        appt.status = AppointmentStatus.booked
        appt.payment_status = "unpaid"

    db.commit()
    return {"message": "Suggestion applied", "fee_delta": fee_delta, "status": appt.status.value}