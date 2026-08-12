from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import date, datetime, timedelta
from pydantic import BaseModel
from typing import Optional
import json

from app.database import get_db
from app.models.doctor import Doctor, UserRole
from app.models.test_order import TestOrder
from app.models.consultation import Consultation
from app.models.patient import Patient
from app.models.test_catalog import TestCatalogItem
from app.models.test_catalog_parameter import TestCatalogParameter
from app.models.hospital import Hospital
from app.models.notifiable_disease import NotifiableDisease
from app.utils.auth import get_current_doctor, ist_today, ist_day_bounds
from app.utils.timezone import now_ist_naive
from app.utils.audit import log_action
from app.utils.order_lifecycle import is_order_expired
from app.routers.attendance import require_present
from app.services.pdf_service import generate_test_report_pdf, generate_combined_test_report_pdf
from fastapi.responses import FileResponse
import os

router = APIRouter(prefix="/lab", tags=["lab"])

VALID_TRANSITIONS = {"sample_collected", "processing", "result_entered"}


def require_lab(current_doctor: Doctor):
    if current_doctor.role.value not in ["lab", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")


def _is_hiv_order(db: Session, order: TestOrder) -> bool:
    if not order.test_id:
        return False
    test = db.query(TestCatalogItem).filter(TestCatalogItem.id == order.test_id).first()
    return bool(test and test.is_hiv_test)


def _require_hiv_access(db: Session, order: TestOrder, current_doctor: Doctor):
    """Tighter than the general lab-role check — an HIV order additionally
    requires admin/sub_admin, or a lab-role account explicitly granted
    is_hiv_authorized (Phase 6 item 21)."""
    if not _is_hiv_order(db, order):
        return
    if current_doctor.role.value in ("admin", "sub_admin"):
        return
    if current_doctor.role.value == "lab" and current_doctor.is_hiv_authorized:
        return
    raise HTTPException(status_code=403, detail="This result requires HIV-access authorization")


def _expected_tat_hours(priority: str) -> float:
    from app.config import settings
    return {
        "stat": settings.LAB_TAT_STAT_HOURS,
        "urgent": settings.LAB_TAT_URGENT_HOURS,
    }.get(priority, settings.LAB_TAT_ROUTINE_HOURS)


def generate_accession_number(db: Session, hospital_id: int, hospital_code: str) -> str:
    """ULR-style, same numbering pattern as generate_token_number in
    patients.py — hospital prefix + date + a daily running count."""
    today = ist_today()
    prefix = hospital_code.replace("-", "")[:4].upper()
    date_part = today.strftime("%d%m%y")
    while True:
        count = db.query(TestOrder).filter(
            TestOrder.hospital_id == hospital_id,
            TestOrder.accessioned_at.isnot(None),
            TestOrder.accessioned_at >= datetime.combine(today, datetime.min.time()),
        ).count() + 1
        number = f"ULR-{prefix}-{date_part}-{count:04d}"
        if not db.query(TestOrder).filter(TestOrder.accession_number == number).first():
            return number


def _check_critical_breach(db: Session, order: TestOrder, results: dict) -> list:
    """Compares entered value(s) against the catalog's configured critical
    thresholds. Panels are checked per-parameter (keyed by parameter name,
    matching how the result-entry screen submits them); simple tests use
    the single 'value' key. Non-numeric entries are silently skipped rather
    than erroring — free-text results (e.g. 'Negative') just can't be
    threshold-checked."""
    test = db.query(TestCatalogItem).filter(TestCatalogItem.id == order.test_id).first() if order.test_id else None
    if not test:
        return []

    breaches = []

    if test.is_panel:
        params = db.query(TestCatalogParameter).filter(
            TestCatalogParameter.test_catalog_item_id == test.id
        ).all()
        param_by_name = {p.name: p for p in params}
        for name, raw_val in (results or {}).items():
            p = param_by_name.get(name)
            if not p or (p.critical_low is None and p.critical_high is None):
                continue
            try:
                val = float(raw_val)
            except (TypeError, ValueError):
                continue
            if p.critical_low is not None and val < p.critical_low:
                breaches.append(f"{name} {val} (critical low — threshold <{p.critical_low})")
            if p.critical_high is not None and val > p.critical_high:
                breaches.append(f"{name} {val} (critical high — threshold >{p.critical_high})")
    else:
        if test.critical_low is not None or test.critical_high is not None:
            raw_val = (results or {}).get("value")
            try:
                val = float(raw_val)
            except (TypeError, ValueError):
                val = None
            if val is not None:
                if test.critical_low is not None and val < test.critical_low:
                    breaches.append(f"{test.name} {val} (critical low — threshold <{test.critical_low})")
                if test.critical_high is not None and val > test.critical_high:
                    breaches.append(f"{test.name} {val} (critical high — threshold >{test.critical_high})")

    return breaches


def _resolve_ordering_context(db: Session, order: TestOrder):
    """Returns (doctor_id, ward, bed_number) regardless of entry channel —
    OPD/emergency via consultation, IPD via admission. Both None if neither
    is set (e.g. a self-pay checkup package with no consultation link),
    in which case the alert still fires hospital-wide, just without a
    targeted doctor ping."""
    if order.admission_id:
        from app.models.admission import Admission
        admission = db.query(Admission).filter(Admission.id == order.admission_id).first()
        if admission:
            return admission.admitting_doctor_id, admission.ward, admission.bed_number
    if order.consultation_id:
        consultation = db.query(Consultation).filter(Consultation.id == order.consultation_id).first()
        if consultation:
            return consultation.doctor_id, None, None
    return None, None, None


def _fire_critical_alert(db: Session, order: TestOrder) -> None:
    """The moment a result crosses a critical threshold — same
    dual-target primitive as the Emergency Alert (targeted doctor + hospital-
    wide admin), applies the same regardless of entry channel."""
    from app.utils.notify import notify_critical_result

    patient = db.query(Patient).filter(Patient.id == order.patient_id).first()
    doctor_id, ward, bed_number = _resolve_ordering_context(db, order)

    notify_critical_result(
        db, hospital_id=order.hospital_id, order_id=order.id,
        patient_name=patient.name if patient else "patient",
        doctor_id=doctor_id, test_name=order.test_name, critical_note=order.critical_note,
        ward=ward, bed_number=bed_number,
    )
    db.commit()

    log_action(
        db, None,
        action="critical_result_notified",
        target_type="test_order",
        target_id=order.id,
        target_label=order.test_name,
        hospital_id=order.hospital_id,
        details=json.dumps({
            "channel": "in_app_notification",  # no SMS/pager integration exists yet
            "notified_doctor_id": doctor_id,
            "notified_admin": True,
            "note": order.critical_note,
        })
    )


class StatusUpdate(BaseModel):
    status: str
    fasting_confirmed: Optional[bool] = None
    drawn_from_iv_line: Optional[bool] = None


class VerifyReleaseIn(BaseModel):
    is_idsp_notifiable: Optional[bool] = False


class ResultIn(BaseModel):
    results: dict


def _escalate_unacknowledged_critical_results(db: Session, hospital_id: int) -> None:
    """No background scheduler in this codebase — same lazy-sweep pattern
    used for online-booking review deadlines. First escalates to
    nurse/ward coverage if the ordering doctor hasn't acknowledged within
    LAB_CRITICAL_ACK_MINUTES, then to admin directly if still unacknowledged
    LAB_CRITICAL_ESCALATION_GRACE_MINUTES after that."""
    from app.config import settings
    from app.utils.notify import notify_critical_result_escalation

    now = now_ist_naive()
    orders = db.query(TestOrder).filter(
        TestOrder.hospital_id == hospital_id,
        TestOrder.is_critical == True,
        TestOrder.critical_ack_at.is_(None),
        TestOrder.critical_detected_at.isnot(None),
    ).all()

    for order in orders:
        ack_deadline = order.critical_detected_at + timedelta(minutes=settings.LAB_CRITICAL_ACK_MINUTES)
        if now < ack_deadline:
            continue

        patient = db.query(Patient).filter(Patient.id == order.patient_id).first()
        _, ward, bed_number = _resolve_ordering_context(db, order)

        if not order.critical_escalated_at:
            notify_critical_result_escalation(
                db, hospital_id=hospital_id, order_id=order.id,
                patient_name=patient.name if patient else "patient",
                test_name=order.test_name, critical_note=order.critical_note,
                stage="nurse_ward", ward=ward, bed_number=bed_number,
            )
            order.critical_escalated_at = now
            db.commit()
            log_action(
                db, None, action="critical_result_escalated", target_type="test_order",
                target_id=order.id, target_label=order.test_name, hospital_id=hospital_id,
                details=json.dumps({"channel": "in_app_notification", "stage": "nurse_ward"})
            )
            continue

        final_deadline = order.critical_escalated_at + timedelta(minutes=settings.LAB_CRITICAL_ESCALATION_GRACE_MINUTES)
        if now < final_deadline:
            continue

        notify_critical_result_escalation(
            db, hospital_id=hospital_id, order_id=order.id,
            patient_name=patient.name if patient else "patient",
            test_name=order.test_name, critical_note=order.critical_note,
            stage="admin", ward=ward, bed_number=bed_number,
        )
        db.commit()
        log_action(
            db, None, action="critical_result_escalated", target_type="test_order",
            target_id=order.id, target_label=order.test_name, hospital_id=hospital_id,
            details=json.dumps({"channel": "in_app_notification", "stage": "admin"})
        )


@router.get("/idsp-notifiable-report")
def get_idsp_notifiable_report(
    start_date: str = None,
    end_date: str = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Pulls every result flagged notifiable within a date range — actual
    submission to IDSP stays a manual/external process, this is just so
    that person isn't re-scanning every single report by hand (Phase 6
    item 23)."""
    require_lab(current_doctor)

    query = db.query(TestOrder).filter(
        TestOrder.hospital_id == current_doctor.hospital_id,
        TestOrder.is_idsp_notifiable == True,
    )
    if start_date:
        query = query.filter(TestOrder.verified_at >= datetime.strptime(start_date, "%Y-%m-%d"))
    if end_date:
        query = query.filter(TestOrder.verified_at < datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1))

    orders = query.order_by(TestOrder.verified_at.desc()).limit(500).all()

    result = []
    for o in orders:
        patient = db.query(Patient).filter(Patient.id == o.patient_id).first()
        catalog_item = db.query(TestCatalogItem).filter(TestCatalogItem.id == o.test_id).first() if o.test_id else None
        disease = db.query(NotifiableDisease).filter(NotifiableDisease.id == catalog_item.notifiable_disease_id).first() if catalog_item and catalog_item.notifiable_disease_id else None
        result.append({
            "order_id": o.id,
            "patient_name": patient.name if patient else "Unknown",
            "patient_uid": patient.patient_uid if patient else None,
            "test_name": o.test_name,
            "disease": disease.name if disease else None,
            "verified_at": o.verified_at.isoformat() if o.verified_at else None,
            "accession_number": o.accession_number,
        })
    return result


@router.get("/hiv-orders")
def list_hiv_orders(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Distinct, restricted view — HIV orders never appear in the general
    queue (see get_lab_queue's exclusion filter). Only admin/sub_admin or
    an explicitly HIV-authorized lab account can see this at all."""
    if current_doctor.role.value not in ("admin", "sub_admin") and not (
        current_doctor.role.value == "lab" and current_doctor.is_hiv_authorized
    ):
        raise HTTPException(status_code=403, detail="This view requires HIV-access authorization")

    hiv_test_ids = [row[0] for row in db.query(TestCatalogItem.id).filter(
        TestCatalogItem.hospital_id == current_doctor.hospital_id, TestCatalogItem.is_hiv_test == True
    ).all()]
    if not hiv_test_ids:
        return []

    orders = db.query(TestOrder).filter(
        TestOrder.hospital_id == current_doctor.hospital_id,
        TestOrder.test_id.in_(hiv_test_ids),
        TestOrder.status != "payment_pending",
    ).order_by(TestOrder.queued_at.desc()).limit(200).all()

    result = []
    for o in orders:
        patient = db.query(Patient).filter(Patient.id == o.patient_id).first()
        result.append({
            "id": o.id,
            "patient_name": patient.name if patient else "Unknown",
            "patient_uid": patient.patient_uid if patient else None,
            "test_name": o.test_name,
            "status": o.status,
            "priority": o.priority,
            "accession_number": o.accession_number,
            "hiv_counselling_completed": o.hiv_counselling_completed,
        })
    return result


@router.post("/hiv-orders/{order_id}/counselling-complete")
def mark_hiv_counselling_complete(
    order_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    order = db.query(TestOrder).filter(
        TestOrder.id == order_id, TestOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Test order not found")
    _require_hiv_access(db, order, current_doctor)

    order.hiv_counselling_completed = True
    db.commit()
    log_action(
        db, current_doctor, action="hiv_counselling_marked_complete", target_type="test_order",
        target_id=order.id, target_label=order.test_name, hospital_id=current_doctor.hospital_id
    )
    return {"id": order.id, "hiv_counselling_completed": True}


@router.get("/queue")
def get_lab_queue(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_lab(current_doctor)
    _escalate_unacknowledged_critical_results(db, current_doctor.hospital_id)

    today_start, today_end = ist_day_bounds()

    hiv_test_ids = [row[0] for row in db.query(TestCatalogItem.id).filter(
        TestCatalogItem.hospital_id == current_doctor.hospital_id, TestCatalogItem.is_hiv_test == True
    ).all()]

    orders = db.query(TestOrder).filter(
        TestOrder.hospital_id == current_doctor.hospital_id,
        TestOrder.status.in_(["paid", "sample_collected", "processing", "result_entered", "verified_released", "rejected"]),
        TestOrder.queued_at >= today_start,
        TestOrder.queued_at <= today_end,
        ~TestOrder.test_id.in_(hiv_test_ids) if hiv_test_ids else True,
    ).order_by(TestOrder.queued_at).all()

    _priority_rank = {"stat": 0, "urgent": 1, "routine": 2}
    orders.sort(key=lambda o: (_priority_rank.get(o.priority, 2), o.queued_at or now_ist_naive()))

    from app.models.admission import Admission

    result = []
    for o in orders:
        patient = db.query(Patient).filter(Patient.id == o.patient_id).first()
        consultation = db.query(Consultation).filter(Consultation.id == o.consultation_id).first()
        catalog_test = db.query(TestCatalogItem).filter(TestCatalogItem.id == o.test_id).first() if o.test_id else None

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
            "test_id": o.test_id,
            "test_name": o.test_name,
            "price": o.price,
            "status": o.status,
            "priority": o.priority,
            "clinical_indication": o.clinical_indication,
            "fasting_required": catalog_test.fasting_required if catalog_test else False,
            "required_tube": catalog_test.required_tube if catalog_test else None,
            "rejection_reason": REJECTION_REASONS.get(o.rejection_reason, o.rejection_reason) if o.rejection_reason else None,
            "sample_condition_caveat": o.sample_condition_caveat,
            "redraw_of_order_id": o.redraw_of_order_id,
            "accession_number": o.accession_number,
            "accessioned_at": o.accessioned_at.isoformat() if o.accessioned_at else None,
            "expected_tat_hours": _expected_tat_hours(o.priority),
            "is_mlc_sample": o.is_mlc_sample,
            "is_overdue": bool(
                o.accessioned_at and o.status not in ("verified_released", "rejected")
                and now_ist_naive() > o.accessioned_at + timedelta(hours=_expected_tat_hours(o.priority))
            ),
            "paid_at": o.paid_at.isoformat() if o.paid_at else None,
            "waiting_minutes": waiting_minutes
        })
    return result


@router.get("/tests/{test_id}")
def get_lab_test_detail(
    test_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Lab-accessible read of a single catalog test's panel parameters (e.g. CBC's
    Hemoglobin/WBC/Platelet sub-tests), used to pre-fill the result entry modal.
    Separate from /admin/tests/{id} which is admin-only."""
    require_lab(current_doctor)

    test = db.query(TestCatalogItem).filter(
        TestCatalogItem.id == test_id,
        TestCatalogItem.hospital_id == current_doctor.hospital_id
    ).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")

    parameters = []
    if test.is_panel:
        rows = db.query(TestCatalogParameter).filter(
            TestCatalogParameter.test_catalog_item_id == test.id,
            TestCatalogParameter.is_active == True
        ).order_by(TestCatalogParameter.display_order).all()
        parameters = [{
            "id": p.id,
            "name": p.name,
            "unit": p.unit or "",
            "reference_range_male": p.reference_range_male or "",
            "reference_range_female": p.reference_range_female or "",
            "critical_low": p.critical_low,
            "critical_high": p.critical_high,
        } for p in rows]

    return {
        "id": test.id,
        "test_name": test.name,
        "is_panel": test.is_panel,
        "unit": test.unit or "",
        "reference_range_male": test.reference_range_male or "",
        "reference_range_female": test.reference_range_female or "",
        "critical_low": test.critical_low,
        "critical_high": test.critical_high,
        "fasting_required": test.fasting_required,
        "required_tube": test.required_tube,
        "notifiable_disease_id": test.notifiable_disease_id,
        "parameters": parameters
    }


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

    today = ist_today()
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

    order.queued_at = now_ist_naive()
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


@router.post("/orders/{order_id}/defer")
def defer_test_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Push a single test out of today's active queue (e.g. fasting-only
    test that can't be done today) without touching any other test on the
    same visit. It reappears via Pending Tasks, same as an order that
    naturally aged out — 'Requeue' there brings it back exactly as before."""
    require_lab(current_doctor)

    order = db.query(TestOrder).filter(
        TestOrder.id == order_id,
        TestOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Test order not found")
    if order.status != "paid":
        raise HTTPException(status_code=400, detail="Only paid, uncollected tests can be deferred")

    today_start, _ = ist_day_bounds()
    order.queued_at = today_start - timedelta(minutes=1)
    db.commit()

    log_action(
        db, current_doctor,
        action="test_order_requeued",
        target_type="test_order",
        target_id=order.id,
        target_label=f"{order.test_name} (deferred)",
        hospital_id=current_doctor.hospital_id
    )
    return {"id": order.id, "status": order.status}


REJECTION_REASONS = {
    "unlabeled_mislabeled": "Unlabeled/mislabeled sample",
    "clotted": "Clotted sample",
    "hemolyzed": "Hemolyzed sample",
    "insufficient_volume": "Insufficient volume",
    "wrong_tube": "Wrong tube/container",
    "container_compromised": "Leaking/broken/contaminated container",
    "past_stability_window": "Past stability window",
    "no_matching_order": "No matching valid order",
}


class RejectSampleIn(BaseModel):
    reason: str


@router.post("/orders/{order_id}/reject")
def reject_sample(
    order_id: int,
    payload: RejectSampleIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Distinct from defer/requeue (which handle an uncollected order) —
    this is for a sample that WAS drawn but is unsuitable. Irreplaceable
    sample types (CSF, biopsy, bone marrow) are never hard-rejected here —
    they get a report caveat instead, per Phase 4 item 14's exception."""
    require_lab(current_doctor)
    if payload.reason not in REJECTION_REASONS:
        raise HTTPException(status_code=400, detail=f"reason must be one of: {', '.join(REJECTION_REASONS)}")

    order = db.query(TestOrder).filter(
        TestOrder.id == order_id,
        TestOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Test order not found")
    _require_hiv_access(db, order, current_doctor)
    if order.status not in ("sample_collected", "processing"):
        raise HTTPException(status_code=400, detail="Only a collected sample can be rejected")

    reason_label = REJECTION_REASONS[payload.reason]
    catalog_test = db.query(TestCatalogItem).filter(TestCatalogItem.id == order.test_id).first() if order.test_id else None

    if order.is_mlc_sample:
        from app.models.mlc_custody import MlcChainOfCustody
        db.add(MlcChainOfCustody(
            test_order_id=order.id, hospital_id=current_doctor.hospital_id,
            stage="rejected", seal_intact=None, notes=f"Rejected: {reason_label}",
            recorded_by=current_doctor.id,
        ))
        db.commit()

    if catalog_test and catalog_test.is_irreplaceable_sample:
        order.sample_condition_caveat = reason_label
        db.commit()
        log_action(
            db, current_doctor, action="sample_condition_caveat_added", target_type="test_order",
            target_id=order.id, target_label=order.test_name, hospital_id=current_doctor.hospital_id,
            details=json.dumps({"reason": payload.reason})
        )
        return {"id": order.id, "status": order.status, "caveat": reason_label}

    order.status = "rejected"
    order.rejection_reason = payload.reason
    order.rejected_at = now_ist_naive()
    order.rejected_by = current_doctor.id
    db.commit()

    # Already-paid redraw clone, ready for immediate re-collection — no
    # repay-then-refund cycle, and the rejected original stays intact as
    # its own historical record.
    redraw = TestOrder(
        consultation_id=order.consultation_id, admission_id=order.admission_id,
        patient_id=order.patient_id, hospital_id=order.hospital_id,
        test_id=order.test_id, test_name=order.test_name, price=0,
        included=order.included, status="paid",
        priority=order.priority, clinical_indication=order.clinical_indication,
        paid_at=now_ist_naive(), queued_at=now_ist_naive(),
        redraw_of_order_id=order.id,
    )
    db.add(redraw)
    db.commit()
    db.refresh(redraw)

    patient = db.query(Patient).filter(Patient.id == order.patient_id).first()
    location = ""
    if order.admission_id:
        from app.models.admission import Admission
        admission = db.query(Admission).filter(Admission.id == order.admission_id).first()
        if admission:
            location = f" — {admission.ward}, Bed {admission.bed_number}"

    from app.models.notification import Notification
    db.add(Notification(
        hospital_id=current_doctor.hospital_id,
        source_key=f"sample_rejected:{order.id}",
        type="sample_rejected", severity="warning",
        title="Sample rejected — redraw needed",
        message=f"{patient.name if patient else 'Patient'}{location}: {order.test_name} rejected ({reason_label}). Redraw requested.",
        link_type="test_order", link_id=redraw.id,
    ))
    db.commit()

    log_action(
        db, current_doctor, action="sample_rejected", target_type="test_order",
        target_id=order.id, target_label=order.test_name, hospital_id=current_doctor.hospital_id,
        details=json.dumps({"reason": payload.reason, "redraw_order_id": redraw.id})
    )
    return {"id": order.id, "status": order.status, "reason": reason_label, "redraw_order_id": redraw.id}


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
    _require_hiv_access(db, order, current_doctor)

    if status == "result_entered" and not order.result_data:
        raise HTTPException(status_code=400, detail="Save the test results before marking this order's entry complete")

    order.status = status
    if status == "sample_collected":
        order.collected_at = now_ist_naive()
        if payload.fasting_confirmed is not None:
            order.fasting_confirmed = payload.fasting_confirmed
        if payload.drawn_from_iv_line is not None:
            order.drawn_from_iv_line = payload.drawn_from_iv_line
    elif status == "processing" and not order.accession_number:
        if order.is_mlc_sample:
            from app.models.mlc_custody import MlcChainOfCustody
            has_lab_receipt = db.query(MlcChainOfCustody).filter(
                MlcChainOfCustody.test_order_id == order.id,
                MlcChainOfCustody.stage == "received_at_lab",
            ).first() is not None
            if not has_lab_receipt:
                raise HTTPException(status_code=400, detail="Log the 'received at lab' chain-of-custody handoff before accessioning this MLC sample")

        hospital = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()
        order.accession_number = generate_accession_number(db, current_doctor.hospital_id, hospital.hospital_code if hospital else "GEN")
        order.accessioned_at = now_ist_naive()
    elif status == "result_entered":
        order.completed_at = now_ist_naive()
        order.completed_by = current_doctor.id

        # If this tech is the only lab-role account at the hospital, the
        # separate verify step is a click with no actual gatekeeping effect
        # (nothing becomes more/less editable after it) — skip straight to
        # released instead of making them tap Verify on their own entry.
        other_lab_staff_exists = db.query(Doctor).filter(
            Doctor.hospital_id == current_doctor.hospital_id,
            Doctor.role == UserRole.lab,
            Doctor.is_active == True,
            Doctor.id != current_doctor.id,
        ).first() is not None
        if not other_lab_staff_exists:
            order.status = "verified_released"
            order.verified_by = current_doctor.id
            order.verified_at = now_ist_naive()
            order.self_verified_sole_staff = True

    db.commit()

    log_action(
        db, current_doctor,
        action="test_order_status_updated",
        target_type="test_order",
        target_id=order.id,
        target_label=f"{order.test_name} -> {order.status}",
        hospital_id=current_doctor.hospital_id
    )
    return {"id": order.id, "status": order.status}


@router.post("/orders/{order_id}/acknowledge-critical")
def acknowledge_critical_result(
    order_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """The ordering doctor (or admin) acknowledges a critical-result alert —
    stops the escalation clock. Distinct from the generic notification
    is_read toggle so this is explicit and auditable."""
    order = db.query(TestOrder).filter(
        TestOrder.id == order_id,
        TestOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Test order not found")
    if not order.is_critical:
        raise HTTPException(status_code=400, detail="This order has no active critical-result alert")

    doctor_id, _, _ = _resolve_ordering_context(db, order)
    if current_doctor.role.value not in ("admin", "sub_admin") and current_doctor.id != doctor_id:
        raise HTTPException(status_code=403, detail="Only the ordering doctor or an admin can acknowledge this")

    order.critical_ack_at = now_ist_naive()
    db.commit()

    log_action(
        db, current_doctor,
        action="critical_result_acknowledged",
        target_type="test_order",
        target_id=order.id,
        target_label=order.test_name,
        hospital_id=current_doctor.hospital_id,
        details=json.dumps({"channel": "in_app_action"})
    )
    return {"id": order.id, "critical_ack_at": order.critical_ack_at.isoformat()}


@router.get("/orders/{order_id}/current-result")
def get_order_current_result(
    order_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Powers the "Edit Report" form for an already-verified_released order —
    the existing report endpoints only ever generate a PDF, nothing returns
    a single order's raw current values as JSON for prefilling an edit."""
    require_lab(current_doctor)
    order = db.query(TestOrder).filter(
        TestOrder.id == order_id,
        TestOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Test order not found")
    _require_hiv_access(db, order, current_doctor)

    try:
        result_data = json.loads(order.result_data or "{}")
    except Exception:
        result_data = {}

    return {"id": order.id, "test_id": order.test_id, "test_name": order.test_name, "status": order.status, "results": result_data}


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
    _require_hiv_access(db, order, current_doctor)

    old_results = {}
    if order.result_data:
        try:
            old_results = json.loads(order.result_data)
        except Exception:
            old_results = {}

    was_already_completed = order.status == "verified_released"
    changed_fields = [k for k in payload.results if old_results.get(k) != payload.results.get(k)]

    order.result_data = json.dumps(payload.results)

    # Critical-value check (Phase 1) — recomputed on every save so a
    # correction that clears a breach un-flags it, and a newly-entered
    # breach on an edit still gets caught.
    was_critical = order.is_critical
    breaches = _check_critical_breach(db, order, payload.results)
    order.is_critical = bool(breaches)
    order.critical_note = "; ".join(breaches) if breaches else None
    if breaches and not was_critical:
        order.critical_detected_at = now_ist_naive()
        order.critical_ack_at = None
        order.critical_escalated_at = None
    elif not breaches:
        order.critical_detected_at = None
        order.critical_ack_at = None
        order.critical_escalated_at = None

    db.commit()

    if breaches and not was_critical:
        _fire_critical_alert(db, order)

    log_action(
        db, current_doctor,
        action="test_result_edited_after_completion" if was_already_completed and changed_fields else "test_result_saved",
        target_type="test_order",
        target_id=order.id,
        target_label=order.test_name,
        hospital_id=current_doctor.hospital_id,
        details=json.dumps({"changed_fields": changed_fields, "old": old_results, "new": payload.results}) if (was_already_completed and changed_fields) else None
    )
    return {"id": order.id, "result_data": payload.results}

@router.post("/orders/{order_id}/verify")
def verify_and_release_result(
    order_id: int,
    body: Optional[VerifyReleaseIn] = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Independent-review gate: no result is visible to the doctor or
    patient portal until this happens. The existing 'lab' role covers
    this — no separate pathologist role invented — but the verifier must
    be a different person than whoever entered the raw result, even in a
    small hospital with only one lab-role account each."""
    require_lab(current_doctor)
    require_present(db, current_doctor)

    order = db.query(TestOrder).filter(
        TestOrder.id == order_id,
        TestOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Test order not found")
    _require_hiv_access(db, order, current_doctor)
    if order.status != "result_entered":
        raise HTTPException(status_code=400, detail="This order isn't awaiting verification")
    self_verified_sole_staff = False
    if order.completed_by and order.completed_by == current_doctor.id:
        other_lab_staff_exists = db.query(Doctor).filter(
            Doctor.hospital_id == current_doctor.hospital_id,
            Doctor.role == UserRole.lab,
            Doctor.is_active == True,
            Doctor.id != current_doctor.id,
        ).first() is not None
        if other_lab_staff_exists:
            raise HTTPException(status_code=403, detail="The person who entered the result can't also verify it — needs independent review")
        self_verified_sole_staff = True  # only one lab-role account exists at this hospital — allowed through, but flagged

    order.status = "verified_released"
    order.verified_by = current_doctor.id
    order.verified_at = now_ist_naive()
    order.self_verified_sole_staff = self_verified_sole_staff
    if body and body.is_idsp_notifiable:
        order.is_idsp_notifiable = True
    db.commit()

    log_action(
        db, current_doctor,
        action="test_result_verified_released",
        target_type="test_order",
        target_id=order.id,
        target_label=order.test_name,
        hospital_id=current_doctor.hospital_id,
    )
    return {"id": order.id, "status": order.status, "verified_at": order.verified_at.isoformat()}


@router.get("/orders/{order_id}/tat-trace")
def get_tat_trace(
    order_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Stage-by-stage handoff timestamps so a delay is traceable to a
    specific stage rather than one opaque total (Phase 5 item 16)."""
    order = db.query(TestOrder).filter(
        TestOrder.id == order_id,
        TestOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Test order not found")

    stages = [
        ("order_placed", "Order Placed", order.created_at),
        ("sample_collected", "Sample Collected", order.collected_at),
        ("sample_accessioned", "Sample Accessioned / Processing Started", order.accessioned_at),
        ("result_entered", "Result Entered", order.completed_at if order.status in ("result_entered", "verified_released") else None),
        ("verified_released", "Verified & Released", order.verified_at),
    ]

    trace = []
    prev_ts = None
    for key, label, ts in stages:
        duration_minutes = None
        if ts and prev_ts:
            duration_minutes = round((ts - prev_ts).total_seconds() / 60, 1)
        trace.append({
            "stage": key,
            "label": label,
            "timestamp": ts.isoformat() if ts else None,
            "minutes_since_previous_stage": duration_minutes,
        })
        if ts:
            prev_ts = ts

    expected_hours = _expected_tat_hours(order.priority)
    expected_deadline = order.accessioned_at + timedelta(hours=expected_hours) if order.accessioned_at else None
    actual_hours = None
    if order.accessioned_at and order.verified_at:
        actual_hours = round((order.verified_at - order.accessioned_at).total_seconds() / 3600, 1)
    is_overdue = bool(
        expected_deadline and order.status not in ("verified_released", "rejected")
        and now_ist_naive() > expected_deadline
    )

    return {
        "order_id": order.id, "test_name": order.test_name, "priority": order.priority,
        "expected_tat_hours": expected_hours,
        "expected_deadline": expected_deadline.isoformat() if expected_deadline else None,
        "actual_tat_hours": actual_hours,
        "is_overdue": is_overdue,
        "stages": trace,
    }


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

    if order.status != "verified_released":
        raise HTTPException(status_code=400, detail="Results not yet available for this test")
    # sample_condition_caveat (irreplaceable-sample path) is read directly
    # off `order` by generate_test_report_pdf below — no extra lookup needed.

    patient = db.query(Patient).filter(Patient.id == order.patient_id).first()
    consultation = db.query(Consultation).filter(Consultation.id == order.consultation_id).first()
    ordering_doctor = db.query(Doctor).filter(Doctor.id == consultation.doctor_id).first() if consultation else None

    if _is_hiv_order(db, order):
        is_ordering_doctor = ordering_doctor and current_doctor.id == ordering_doctor.id
        if not is_ordering_doctor:
            _require_hiv_access(db, order, current_doctor)
    lab_staff = db.query(Doctor).filter(Doctor.id == order.verified_by).first() if order.verified_by else None
    catalog_test = db.query(TestCatalogItem).filter(TestCatalogItem.id == order.test_id).first() if order.test_id else None
    catalog_item = db.query(TestCatalogItem).filter(TestCatalogItem.id == order.test_id).first() if order.test_id else None

    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    filepath = generate_test_report_pdf(
        order=order,
        patient=patient,
        catalog_item=catalog_item,
        ordering_doctor=ordering_doctor,
        lab_staff=lab_staff,
        hospital=current_doctor.hospital
    )

    return FileResponse(filepath, media_type="application/pdf", filename=os.path.basename(filepath))


@router.get("/patient-reports/{patient_id}")
def get_patient_reports(
    patient_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Read-only, date-wise test report history for one patient — used by the
    Reports button on patient.html and consultation.html. Doesn't touch any
    consultation/recording state; open to any staff role at the hospital,
    same as the rest of a patient's chart."""
    patient = db.query(Patient).filter(
        Patient.id == patient_id,
        Patient.hospital_id == current_doctor.hospital_id
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    orders = db.query(TestOrder).filter(
        TestOrder.patient_id == patient_id,
        TestOrder.hospital_id == current_doctor.hospital_id,
        TestOrder.status == "verified_released"
    ).order_by(TestOrder.verified_at.desc()).all()

    visible_orders = []
    for o in orders:
        if _is_hiv_order(db, o):
            consultation = db.query(Consultation).filter(Consultation.id == o.consultation_id).first()
            is_ordering_doctor = consultation and consultation.doctor_id == current_doctor.id
            if not is_ordering_doctor:
                try:
                    _require_hiv_access(db, o, current_doctor)
                except HTTPException:
                    continue
        visible_orders.append(o)

    visits = {}
    for o in visible_orders:
        key = o.consultation_id
        if key not in visits:
            consultation = db.query(Consultation).filter(Consultation.id == o.consultation_id).first()
            visits[key] = {
                "consultation_id": o.consultation_id,
                "token_number": consultation.token_number if consultation else "",
                "date": None,
                "tests": [],
            }
        v = visits[key]
        completed_iso = o.completed_at.isoformat() if o.completed_at else None
        if completed_iso and (v["date"] is None or completed_iso > v["date"]):
            v["date"] = completed_iso

        # result_data on the order is just {param_name: value} — no unit or
        # reference range travels with it, that lives on the catalog. Build
        # a proper row list (name/value/unit/range) here so the doctor-side
        # modal can render it as a real table instead of a flat key:value dump.
        try:
            raw_results = json.loads(o.result_data) if o.result_data else {}
        except Exception:
            raw_results = {}
        catalog_item = db.query(TestCatalogItem).filter(TestCatalogItem.id == o.test_id).first() if o.test_id else None
        is_male = (patient.gender or "").lower() == "male"
        rows = []
        if catalog_item and catalog_item.is_panel:
            params = db.query(TestCatalogParameter).filter(
                TestCatalogParameter.test_catalog_item_id == catalog_item.id,
                TestCatalogParameter.is_active == True
            ).order_by(TestCatalogParameter.display_order).all()
            for p in params:
                if p.name not in raw_results:
                    continue
                rows.append({
                    "name": p.name,
                    "value": raw_results.get(p.name, ""),
                    "unit": p.unit or "",
                    "range": (p.reference_range_male if is_male else p.reference_range_female) or "",
                })
        elif raw_results:
            range_str = (catalog_item.reference_range_male if is_male else catalog_item.reference_range_female) if catalog_item else ""
            rows.append({
                "name": o.test_name,
                "value": raw_results.get("value", ""),
                "unit": (catalog_item.unit if catalog_item else "") or "",
                "range": range_str or "",
            })

        v["tests"].append({
            "order_id": o.id,
            "test_name": o.test_name,
            "results": rows,
            "is_critical": o.is_critical,
            "verified_at": o.verified_at.isoformat() if o.verified_at else None,
        })

    result = list(visits.values())
    result.sort(key=lambda v: v["date"] or "", reverse=True)
    return result


@router.get("/reports/history")
def get_lab_reports_history(
    q: str = "",
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_lab(current_doctor)

    orders = db.query(TestOrder).filter(
        TestOrder.hospital_id == current_doctor.hospital_id,
        TestOrder.status == "verified_released"
    ).order_by(TestOrder.verified_at.desc()).limit(500).all()

    # One "visit" per (patient, consultation) — this is a single day's tests.
    visit_groups = {}
    for o in orders:
        key = (o.patient_id, o.consultation_id)
        if key not in visit_groups:
            visit_groups[key] = {
                "order_ids": [], "test_names": [], "completed_at": None,
                "patient_id": o.patient_id, "consultation_id": o.consultation_id
            }
        v = visit_groups[key]
        v["order_ids"].append(o.id)
        v["test_names"].append(o.test_name)
        completed_iso = o.completed_at.isoformat() if o.completed_at else None
        if completed_iso and (v["completed_at"] is None or completed_iso > v["completed_at"]):
            v["completed_at"] = completed_iso

    # Roll visits up under their patient — one entry per patient in the main list.
    patients_map = {}
    for v in visit_groups.values():
        consultation = db.query(Consultation).filter(Consultation.id == v["consultation_id"]).first()
        entry = patients_map.setdefault(v["patient_id"], {"patient_id": v["patient_id"], "visits": []})
        entry["visits"].append({
            "consultation_id": v["consultation_id"],
            "token_number": consultation.token_number if consultation else "",
            "test_names": v["test_names"],
            "order_ids": v["order_ids"],
            "completed_at": v["completed_at"]
        })

    q_lower = q.strip().lower()
    result = []
    for entry in patients_map.values():
        patient = db.query(Patient).filter(Patient.id == entry["patient_id"]).first()
        patient_name = patient.name if patient else "Unknown"
        patient_uid = patient.patient_uid if patient else ""
        if q_lower and q_lower not in patient_name.lower() and q_lower not in patient_uid.lower():
            continue
        entry["visits"].sort(key=lambda v: v["completed_at"] or "", reverse=True)
        result.append({
            "patient_id": entry["patient_id"],
            "patient_name": patient_name,
            "patient_uid": patient_uid,
            "visits": entry["visits"],
            "latest_completed_at": entry["visits"][0]["completed_at"] if entry["visits"] else None
        })

    result.sort(key=lambda r: r["latest_completed_at"] or "", reverse=True)
    return result


@router.get("/reports/combined")
def get_combined_test_report(
    order_ids: str,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    ids = [int(x) for x in order_ids.split(",") if x.strip().isdigit()]
    if not ids:
        raise HTTPException(status_code=400, detail="No order IDs provided")

    orders = db.query(TestOrder).filter(
        TestOrder.id.in_(ids),
        TestOrder.hospital_id == current_doctor.hospital_id
    ).all()
    if not orders:
        raise HTTPException(status_code=404, detail="No matching test orders found")

    if len(set(o.patient_id for o in orders)) > 1:
        raise HTTPException(status_code=400, detail="All orders must belong to the same patient")

    if any(o.status != "verified_released" for o in orders):
        raise HTTPException(status_code=400, detail="Some results are not yet verified and released")

    patient = db.query(Patient).filter(Patient.id == orders[0].patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    consultation = db.query(Consultation).filter(Consultation.id == orders[0].consultation_id).first()
    ordering_doctor = db.query(Doctor).filter(Doctor.id == consultation.doctor_id).first() if consultation else None

    for o in orders:
        if _is_hiv_order(db, o):
            is_ordering_doctor = ordering_doctor and current_doctor.id == ordering_doctor.id
            if not is_ordering_doctor:
                _require_hiv_access(db, o, current_doctor)
    lab_staff_id = next((o.verified_by for o in orders if o.verified_by), None)
    lab_staff = db.query(Doctor).filter(Doctor.id == lab_staff_id).first() if lab_staff_id else None

    is_male = (patient.gender or "").lower() == "male"

    tests_payload = []
    for order in orders:
        catalog_item = db.query(TestCatalogItem).filter(TestCatalogItem.id == order.test_id).first() if order.test_id else None
        try:
            result_data = json.loads(order.result_data or "{}")
        except Exception:
            result_data = {}

        if catalog_item and catalog_item.is_panel:
            params = db.query(TestCatalogParameter).filter(
                TestCatalogParameter.test_catalog_item_id == catalog_item.id,
                TestCatalogParameter.is_active == True
            ).order_by(TestCatalogParameter.display_order).all()
            rows = [{
                "name": p.name,
                "unit": p.unit or "",
                "range": (p.reference_range_male if is_male else p.reference_range_female) or "",
                "value": result_data.get(p.name, "")
            } for p in params if result_data.get(p.name)]  # untested subtests are excluded from the final report entirely
        else:
            range_str = ""
            unit = ""
            if catalog_item:
                range_str = (catalog_item.reference_range_male if is_male else catalog_item.reference_range_female) or ""
                unit = catalog_item.unit or ""
            rows = [{
                "name": order.test_name,
                "unit": unit,
                "range": range_str,
                "value": result_data.get("value", "")
            }]

        tests_payload.append({
            "test_name": order.test_name,
            "rows": rows,
            "notes": result_data.get("notes", ""),
            "fasting_confirmed": order.fasting_confirmed,
            "drawn_from_iv_line": order.drawn_from_iv_line,
            "sample_condition_caveat": order.sample_condition_caveat,
            "collected_at": order.collected_at,
            "accession_number": order.accession_number,
            "accessioned_at": order.accessioned_at,
            "verified_at": order.verified_at,
            "is_nabl_accredited": catalog_item.is_nabl_accredited if catalog_item else False,
        })

    filepath = generate_combined_test_report_pdf(
        order_id_key=f"{orders[0].patient_id}_{'-'.join(str(o.id) for o in orders)}",
        tests_payload=tests_payload,
        patient=patient,
        ordering_doctor=ordering_doctor,
        lab_staff=lab_staff,
        hospital=current_doctor.hospital
    )

    return FileResponse(filepath, media_type="application/pdf", filename=os.path.basename(filepath))