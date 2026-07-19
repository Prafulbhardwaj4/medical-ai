from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.portal import Appointment, AppointmentStatus, AppointmentType, PatientAccount
from app.schemas.portal import BookAppointmentIn, AppointmentOut
from app.utils.portal_auth import get_current_patient_account

router = APIRouter(prefix="/portal/appointments", tags=["portal-appointments"])


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

    appt = Appointment(
        account_id=account.id,
        profile_link_id=body.profile_link_id,
        hospital_id=body.hospital_id,
        doctor_id=body.doctor_id,
        type=AppointmentType(body.type),
        requested_time=body.requested_time,
        notes=body.notes,
        status=AppointmentStatus.booked,
    )
    db.add(appt)
    db.commit()
    db.refresh(appt)
    return appt


@router.get("", response_model=list[AppointmentOut])
def list_my_appointments(account: PatientAccount = Depends(get_current_patient_account)):
    return account.appointments


@router.post("/{appointment_id}/cancel", response_model=AppointmentOut)
def cancel_appointment(
    appointment_id: int,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    appt = next((a for a in account.appointments if a.id == appointment_id), None)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    appt.status = AppointmentStatus.cancelled
    db.commit()
    db.refresh(appt)
    return appt