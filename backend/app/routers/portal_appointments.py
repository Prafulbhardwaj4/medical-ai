from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.portal import Appointment, AppointmentStatus, AppointmentType, PatientAccount
from app.models.doctor_slot import DoctorSlot
from app.models.doctor import Doctor
from app.models.hospital import Hospital
from app.schemas.portal import BookAppointmentIn, AppointmentOut
from app.utils.portal_auth import get_current_patient_account

router = APIRouter(prefix="/portal/appointments", tags=["portal-appointments"])


def _to_out(a: Appointment, db: Session) -> AppointmentOut:
    hospital = db.query(Hospital).filter(Hospital.id == a.hospital_id).first()
    doctor = db.query(Doctor).filter(Doctor.id == a.doctor_id).first() if a.doctor_id else None
    return AppointmentOut(
        id=a.id, hospital_id=a.hospital_id, hospital_name=hospital.name if hospital else None,
        doctor_id=a.doctor_id, doctor_name=f"{doctor.title} {doctor.name}" if doctor else None,
        type=a.type.value, requested_time=a.requested_time, status=a.status.value,
        payment_status=a.payment_status, notes=a.notes, address=a.address,
    )


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
        slot = db.query(DoctorSlot).filter(
            DoctorSlot.id == body.slot_id, DoctorSlot.hospital_id == body.hospital_id
        ).first()
        if not slot:
            raise HTTPException(status_code=404, detail="Slot not found")
        if slot.booked_count >= slot.capacity:
            raise HTTPException(status_code=400, detail="This slot just filled up. Please pick another.")

        from app.models.doctor_availability import DoctorUnavailability
        if db.query(DoctorUnavailability).filter(
            DoctorUnavailability.doctor_id == slot.doctor_id, DoctorUnavailability.date == slot.slot_date
        ).first():
            raise HTTPException(status_code=400, detail="This doctor is unavailable on this date. Please pick another date or doctor.")

        slot.booked_count += 1
        doctor_id = slot.doctor_id
        requested_time = datetime.combine(slot.slot_date, datetime.strptime(slot.slot_time, "%H:%M").time())
        slot_id = slot.id
    else:
        from app.utils.timezone import now_ist_naive
        requested_time = now_ist_naive()

    if body.use_saved_address:
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
    appt.payment_status = "paid"
    appt.status = AppointmentStatus.confirmed
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

    if appt.slot_id:
        slot = db.query(DoctorSlot).filter(DoctorSlot.id == appt.slot_id).first()
        if slot and slot.booked_count > 0:
            slot.booked_count -= 1

    appt.status = AppointmentStatus.cancelled
    db.commit()
    db.refresh(appt)
    return _to_out(appt, db)