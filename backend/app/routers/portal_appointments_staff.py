"""Hospital-staff-facing view of patient portal appointments. Read-only —
reception's check-in flow itself is untouched; this just gives visibility
into who has booked or reserved a queue-from-home slot for today."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.portal import Appointment, AppointmentStatus
from app.models.patient import Patient
from app.utils.auth import get_current_doctor
from app.utils.timezone import now_ist_naive

router = APIRouter(prefix="/portal-appointments-staff", tags=["portal-appointments-staff"])


@router.get("/today")
def list_expected_today(
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    today_start = datetime.combine(now_ist_naive().date(), datetime.min.time())
    today_end = today_start + timedelta(days=1)

    appts = (
        db.query(Appointment)
        .filter(
            Appointment.hospital_id == current_doctor.hospital_id,
            Appointment.status.in_([AppointmentStatus.booked, AppointmentStatus.confirmed]),
            Appointment.requested_time >= today_start,
            Appointment.requested_time < today_end,
        )
        .order_by(Appointment.requested_time)
        .all()
    )

    result = []
    for a in appts:
        patient_name = None
        if a.profile_link_id and a.profile_link and a.profile_link.patient:
            patient_name = a.profile_link.patient.name
        result.append({
            "id": a.id,
            "type": a.type.value,
            "requested_time": a.requested_time.isoformat(),
            "status": a.status.value,
            "notes": a.notes,
            "patient_name": patient_name,
        })
    return result