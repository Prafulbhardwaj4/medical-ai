from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.portal import Appointment, AppointmentStatus
from app.models.doctor import Doctor
from app.utils.auth import get_current_doctor
from app.utils.timezone import now_ist_naive

router = APIRouter(prefix="/portal-appointments-staff", tags=["portal-appointments-staff"])


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