from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.portal import Appointment, AppointmentStatus
from app.models.doctor import Doctor
from app.utils.auth import get_current_doctor
from app.utils.timezone import now_ist_naive

router = APIRouter(prefix="/portal-appointments-staff", tags=["portal-appointments-staff"])


@router.get("/today")
def list_expected_today(
    doctor_id: int = Query(None),
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
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
        })
    return {"count": len(result), "appointments": result}