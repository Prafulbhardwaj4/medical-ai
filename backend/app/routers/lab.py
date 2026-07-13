from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import date, datetime
from pydantic import BaseModel
from typing import Optional
import json

from app.database import get_db
from app.models.doctor import Doctor
from app.models.test_order import TestOrder
from app.models.consultation import Consultation
from app.models.patient import Patient
from app.models.test_catalog import TestCatalogItem
from app.utils.auth import get_current_doctor
from app.utils.audit import log_action
from app.utils.order_lifecycle import is_order_expired
from app.routers.attendance import require_present
from app.services.pdf_service import generate_test_report_pdf
from fastapi.responses import FileResponse
import os

router = APIRouter(prefix="/lab", tags=["lab"])

VALID_TRANSITIONS = {"sample_collected", "processing", "completed"}


def require_lab(current_doctor: Doctor):
    if current_doctor.role.value not in ["lab", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")


class StatusUpdate(BaseModel):
    status: str


class ResultIn(BaseModel):
    results: dict


@router.get("/queue")
def get_lab_queue(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_lab(current_doctor)

    today_start = datetime.combine(date.today(), datetime.min.time())
    today_end = datetime.combine(date.today(), datetime.max.time())

    orders = db.query(TestOrder).filter(
        TestOrder.hospital_id == current_doctor.hospital_id,
        TestOrder.status.in_(["paid", "sample_collected", "processing", "completed"]),
        TestOrder.queued_at >= today_start,
        TestOrder.queued_at <= today_end
    ).order_by(TestOrder.queued_at).all()

    result = []
    for o in orders:
        patient = db.query(Patient).filter(Patient.id == o.patient_id).first()
        consultation = db.query(Consultation).filter(Consultation.id == o.consultation_id).first()

        waiting_minutes = None
        if o.paid_at:
            waiting_minutes = int((datetime.utcnow() - o.paid_at).total_seconds() // 60)

        result.append({
            "id": o.id,
            "patient_name": patient.name if patient else "Unknown",
            "token_number": consultation.token_number if consultation else "",
            "test_name": o.test_name,
            "price": o.price,
            "status": o.status,
            "paid_at": o.paid_at.isoformat() if o.paid_at else None,
            "waiting_minutes": waiting_minutes
        })
    return result


@router.get("/pending-tasks")
def search_pending_lab_tasks(
    q: str = "",
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Patient-ID/name search for paid-but-not-completed tests that fell out
    of today's active queue — free, repeatable, one-click requeue, as long
    as still inside the 7-day/next-consultation window."""
    require_lab(current_doctor)
    query = db.query(Patient).filter(Patient.hospital_id == current_doctor.hospital_id)
    if q and len(q.strip()) >= 2:
        like = f"%{q.strip()}%"
        query = query.filter((Patient.name.ilike(like)) | (Patient.patient_uid.ilike(like)))
        patients = query.limit(15).all()
    else:
        # No search yet — list everyone with a pending task, most recent first
        patients = query.join(TestOrder, TestOrder.patient_id == Patient.id).filter(
            TestOrder.hospital_id == current_doctor.hospital_id,
            TestOrder.status == "paid"
        ).distinct().order_by(Patient.id.desc()).limit(30).all()

    today = date.today()
    result = []
    for p in patients:
        orders = db.query(TestOrder).filter(
            TestOrder.patient_id == p.id,
            TestOrder.hospital_id == current_doctor.hospital_id,
            TestOrder.status == "paid"
        ).all()

        pending = []
        for o in orders:
            if o.queued_at and o.queued_at.date() == today:
                continue  # already active in today's queue
            if is_order_expired(db, p.id, o.consultation_id, o.created_at):
                continue
            consultation = db.query(Consultation).filter(Consultation.id == o.consultation_id).first()
            ordering_doctor = db.query(Doctor).filter(Doctor.id == consultation.doctor_id).first() if consultation else None
            pending.append({
                "order_id": o.id,
                "test_name": o.test_name,
                "price": o.price,
                "doctor_name": f"{ordering_doctor.title} {ordering_doctor.name}" if ordering_doctor else "—",
                "paid_at": o.paid_at.isoformat() if o.paid_at else None
            })

        if pending:
            result.append({
                "patient_id": p.id,
                "patient_name": p.name,
                "patient_uid": p.patient_uid,
                "pending": pending
            })
    return result


@router.post("/orders/{order_id}/requeue")
def requeue_test_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_lab(current_doctor)

    order = db.query(TestOrder).filter(
        TestOrder.id == order_id,
        TestOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Test order not found")
    if order.status != "paid":
        raise HTTPException(status_code=400, detail="Only paid, uncollected tests can be requeued")
    if is_order_expired(db, order.patient_id, order.consultation_id, order.created_at):
        raise HTTPException(status_code=400, detail="This order's window has closed — a fresh order is needed")

    order.queued_at = datetime.utcnow()
    db.commit()

    log_action(
        db, current_doctor,
        action="test_order_requeued",
        target_type="test_order",
        target_id=order.id,
        target_label=order.test_name,
        hospital_id=current_doctor.hospital_id
    )
    return {"id": order.id, "queued_at": order.queued_at.isoformat()}


@router.patch("/orders/{order_id}/status")
def update_order_status(
    order_id: int,
    payload: StatusUpdate,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_lab(current_doctor)
    require_present(db, current_doctor)

    status = payload.status.strip().lower()
    if status not in VALID_TRANSITIONS:
        raise HTTPException(status_code=400, detail=f"status must be one of {', '.join(VALID_TRANSITIONS)}")

    order = db.query(TestOrder).filter(
        TestOrder.id == order_id,
        TestOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Test order not found")

    order.status = status
    if status == "sample_collected":
        order.collected_at = datetime.utcnow()
    elif status == "completed":
        order.completed_at = datetime.utcnow()
        order.completed_by = current_doctor.id

    db.commit()

    log_action(
        db, current_doctor,
        action="test_order_status_updated",
        target_type="test_order",
        target_id=order.id,
        target_label=f"{order.test_name} -> {status}",
        hospital_id=current_doctor.hospital_id
    )
    return {"id": order.id, "status": order.status}


@router.post("/orders/{order_id}/result")
def save_order_result(
    order_id: int,
    payload: ResultIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_lab(current_doctor)
    require_present(db, current_doctor)

    order = db.query(TestOrder).filter(
        TestOrder.id == order_id,
        TestOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Test order not found")

    order.result_data = json.dumps(payload.results)
    db.commit()

    log_action(
        db, current_doctor,
        action="test_result_saved",
        target_type="test_order",
        target_id=order.id,
        target_label=order.test_name,
        hospital_id=current_doctor.hospital_id
    )
    return {"id": order.id, "result_data": payload.results}

@router.get("/orders/{order_id}/report")
def get_test_report(
    order_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    order = db.query(TestOrder).filter(
        TestOrder.id == order_id,
        TestOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Test order not found")

    if order.status != "completed":
        raise HTTPException(status_code=400, detail="Results not yet available for this test")

    patient = db.query(Patient).filter(Patient.id == order.patient_id).first()
    consultation = db.query(Consultation).filter(Consultation.id == order.consultation_id).first()
    ordering_doctor = db.query(Doctor).filter(Doctor.id == consultation.doctor_id).first() if consultation else None
    lab_staff = db.query(Doctor).filter(Doctor.id == order.completed_by).first() if order.completed_by else None
    catalog_item = db.query(TestCatalogItem).filter(TestCatalogItem.id == order.test_id).first() if order.test_id else None

    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    filepath = generate_test_report_pdf(
        order=order,
        patient=patient,
        catalog_item=catalog_item,
        ordering_doctor=ordering_doctor,
        lab_staff=lab_staff,
        hospital_name=current_doctor.clinic_name
    )

    return FileResponse(filepath, media_type="application/pdf", filename=os.path.basename(filepath))