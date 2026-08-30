from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional, Dict
from pydantic import BaseModel
import json

import os
from fastapi.responses import FileResponse
from app.database import get_db
from app.models.doctor import Doctor, UserRole
from app.models.radiology_order import RadiologyOrder
from app.models.radiology_template import RadiologyTemplate
from app.models.radiology_template_section import RadiologyTemplateSection
from app.models.consultation import Consultation
from app.models.patient import Patient
from app.utils.auth import get_current_doctor, ist_day_bounds
from app.utils.timezone import now_ist_naive
from app.utils.audit import log_action
from app.routers.attendance import require_present
from app.services.pdf_service import generate_radiology_report_pdf

router = APIRouter(prefix="/radiology", tags=["radiology"])


def require_radiology(current_doctor: Doctor):
    if current_doctor.role.value not in ["radiology", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")


class ReportIn(BaseModel):
    sections: Dict[str, str] = {}
    impression: str = ""
    advised: str = ""


class VerifyReleaseIn(BaseModel):
    pass


def _serialize_radiology_orders(db: Session, orders: list) -> list:
    from app.models.admission import Admission
    result = []
    for o in orders:
        patient = db.query(Patient).filter(Patient.id == o.patient_id).first()
        consultation = db.query(Consultation).filter(Consultation.id == o.consultation_id).first()

        admission_ward = None
        admission_bed = None
        if o.admission_id:
            admission = db.query(Admission).filter(Admission.id == o.admission_id).first()
            if admission:
                admission_ward = admission.ward
                admission_bed = admission.bed_number

        waiting_minutes = None
        if o.paid_at:
            waiting_minutes = int((now_ist_naive() - o.paid_at).total_seconds() // 60)

        result.append({
            "id": o.id,
            "patient_id": o.patient_id,
            "patient_name": patient.name if patient else "Unknown",
            "patient_uid": patient.patient_uid if patient else "",
            "patient_gender": patient.gender if patient else None,
            "token_number": consultation.token_number if consultation else "",
            "is_admission": o.admission_id is not None,
            "ward": admission_ward,
            "bed_number": admission_bed,
            "template_id": o.template_id,
            "study_name": o.study_name,
            "study_type": o.study_type,
            "price": o.price,
            "status": o.status,
            "priority": o.priority,
            "clinical_indication": o.clinical_indication,
            "paid_at": o.paid_at.isoformat() if o.paid_at else None,
            "waiting_minutes": waiting_minutes,
        })
    return result


@router.get("/queue")
def get_radiology_queue(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_radiology(current_doctor)

    today_start, today_end = ist_day_bounds()

    # Unlike lab, this is a single combined queue for both OPD and IPD —
    # radiology has no sample-collection scheduling complexity (accession
    # numbers, overdue-sample tracking) that justified splitting lab into
    # /queue (today's OPD) and /admission-queue (open-ended IPD). OPD
    # imaging is still bounded to today; IPD stays open until reported.
    orders = db.query(RadiologyOrder).filter(
        RadiologyOrder.hospital_id == current_doctor.hospital_id,
        RadiologyOrder.status.in_(["paid", "reported", "verified_released"]),
        (
            (RadiologyOrder.admission_id.isnot(None)) |
            ((RadiologyOrder.admission_id.is_(None)) & (RadiologyOrder.queued_at >= today_start) & (RadiologyOrder.queued_at <= today_end))
        ),
    ).order_by(RadiologyOrder.queued_at).all()

    _priority_rank = {"stat": 0, "urgent": 1, "routine": 2}
    orders.sort(key=lambda o: (_priority_rank.get(o.priority, 2), o.queued_at or now_ist_naive()))

    return _serialize_radiology_orders(db, orders)


@router.get("/orders/{order_id}")
def get_radiology_order_detail(
    order_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_radiology(current_doctor)

    order = db.query(RadiologyOrder).filter(
        RadiologyOrder.id == order_id,
        RadiologyOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Radiology order not found")

    patient = db.query(Patient).filter(Patient.id == order.patient_id).first()

    saved_sections = {}
    if order.sections_data:
        try:
            saved_sections = json.loads(order.sections_data)
        except Exception:
            saved_sections = {}

    # Template auto-load (item 5): every section starts at its "normal"
    # default — a saved value (if this report was already started/edited)
    # always wins over the template default, section by section.
    sections_out = []
    if order.template_id:
        template_sections = db.query(RadiologyTemplateSection).filter(
            RadiologyTemplateSection.radiology_template_id == order.template_id,
            RadiologyTemplateSection.is_active == True
        ).order_by(RadiologyTemplateSection.display_order).all()
        for s in template_sections:
            sections_out.append({
                "name": s.name,
                "text": saved_sections.get(s.name, s.default_finding_text or ""),
            })
    else:
        # No template (e.g. an ad-hoc/manual study) — nothing to seed from,
        # radiologist starts with whatever was already saved, if anything.
        sections_out = [{"name": k, "text": v} for k, v in saved_sections.items()]

    return {
        "id": order.id,
        "patient": {"id": patient.id, "name": patient.name, "age": patient.age, "gender": patient.gender, "patient_uid": patient.patient_uid} if patient else None,
        "study_name": order.study_name,
        "study_type": order.study_type,
        "status": order.status,
        "priority": order.priority,
        "clinical_indication": order.clinical_indication,
        "sections": sections_out,
        "impression": order.impression or "",
        "advised": order.advised or "",
        "reported_at": order.reported_at.isoformat() if order.reported_at else None,
        "verified_at": order.verified_at.isoformat() if order.verified_at else None,
    }


@router.post("/orders/{order_id}/report")
def save_radiology_report(
    order_id: int,
    payload: ReportIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_radiology(current_doctor)
    require_present(db, current_doctor)

    order = db.query(RadiologyOrder).filter(
        RadiologyOrder.id == order_id,
        RadiologyOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Radiology order not found")

    was_already_completed = order.status == "verified_released"

    order.sections_data = json.dumps(payload.sections)
    order.impression = payload.impression
    order.advised = payload.advised
    if order.status == "paid":
        order.status = "reported"
    order.reported_at = now_ist_naive()
    order.reported_by = current_doctor.id
    db.commit()

    log_action(
        db, current_doctor,
        action="radiology_report_edited_after_completion" if was_already_completed else "radiology_report_saved",
        target_type="radiology_order",
        target_id=order.id,
        target_label=order.study_name,
        hospital_id=current_doctor.hospital_id,
    )
    return {"id": order.id, "status": order.status}


@router.post("/orders/{order_id}/verify")
def verify_and_release_radiology_report(
    order_id: int,
    body: Optional[VerifyReleaseIn] = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Same independent-review gate as lab's verify step — the verifier
    must be a different person than whoever wrote the report, even at a
    small hospital with only one radiology-role account."""
    require_radiology(current_doctor)
    require_present(db, current_doctor)

    order = db.query(RadiologyOrder).filter(
        RadiologyOrder.id == order_id,
        RadiologyOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Radiology order not found")
    if order.status != "reported":
        raise HTTPException(status_code=400, detail="This report isn't awaiting verification")

    self_verified_sole_staff = False
    if order.reported_by and order.reported_by == current_doctor.id:
        other_radiology_staff_exists = db.query(Doctor).filter(
            Doctor.hospital_id == current_doctor.hospital_id,
            Doctor.role == UserRole.radiology,
            Doctor.is_active == True,
            Doctor.id != current_doctor.id,
        ).first() is not None
        if other_radiology_staff_exists:
            raise HTTPException(status_code=403, detail="The person who wrote the report can't also verify it — needs independent review")
        self_verified_sole_staff = True

    order.status = "verified_released"
    order.verified_by = current_doctor.id
    order.verified_at = now_ist_naive()
    order.self_verified_sole_staff = self_verified_sole_staff
    db.commit()

    log_action(
        db, current_doctor,
        action="radiology_report_verified_released",
        target_type="radiology_order",
        target_id=order.id,
        target_label=order.study_name,
        hospital_id=current_doctor.hospital_id,
    )
    return {"id": order.id, "status": order.status, "verified_at": order.verified_at.isoformat()}


@router.get("/orders/{order_id}/pdf")
def get_radiology_report_pdf(
    order_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    order = db.query(RadiologyOrder).filter(
        RadiologyOrder.id == order_id,
        RadiologyOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Radiology order not found")
    if order.status != "verified_released":
        raise HTTPException(status_code=400, detail="Report not yet available for this study")

    patient = db.query(Patient).filter(Patient.id == order.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    ordering_doctor = None
    if order.admission_id:
        from app.models.admission import Admission
        admission = db.query(Admission).filter(Admission.id == order.admission_id).first()
        if admission and admission.admitting_doctor_id:
            ordering_doctor = db.query(Doctor).filter(Doctor.id == admission.admitting_doctor_id).first()
    elif order.consultation_id:
        consultation = db.query(Consultation).filter(Consultation.id == order.consultation_id).first()
        ordering_doctor = db.query(Doctor).filter(Doctor.id == consultation.doctor_id).first() if consultation else None

    radiology_staff = db.query(Doctor).filter(Doctor.id == order.verified_by).first() if order.verified_by else None

    filepath = generate_radiology_report_pdf(
        order=order, patient=patient, ordering_doctor=ordering_doctor,
        radiology_staff=radiology_staff, hospital=current_doctor.hospital
    )
    return FileResponse(filepath, media_type="application/pdf", filename=os.path.basename(filepath))