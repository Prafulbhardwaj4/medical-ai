from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.portal import PatientAccount
from app.models.patient import Patient
from app.models.consultation import Consultation
from app.models.test_order import TestOrder
from app.models.invoice import Invoice
from app.models.checkin import Checkin
from app.models.hospital import Hospital
from app.models.doctor import Doctor
from app.models.admission import Admission, AdmissionMedicationOrder
from app.models.test_catalog import TestCatalogItem
from app.models.test_catalog_parameter import TestCatalogParameter
from app.schemas.portal import DashboardStatsOut, ProfileSummaryOut, VisitOut, VisitDetailOut, VisitTestOut, AdmissionSummaryOut, VisitFeedbackIn, PortalSuggestionIn
from app.utils.portal_auth import get_current_patient_account
from app.utils.auth import get_current_doctor
from app.utils.timezone import now_ist_naive
from app.services.pdf_service import generate_prescription_pdf, generate_invoice_pdf, generate_combined_test_report_pdf
import json
import os

router = APIRouter(prefix="/portal/dashboard", tags=["portal-dashboard"])


def _owned_patient_ids(account: PatientAccount) -> set:
    # Pending-confirmation links haven't been confirmed as "theirs" yet —
    # exclude them everywhere history/documents/stats are built, so nothing
    # from a possibly-different person silently shows up as this patient's
    # own medical history.
    return {link.patient_id for link in account.profiles if link.relation != "pending_confirmation"}


@router.get("/stats", response_model=DashboardStatsOut)
def get_stats(account: PatientAccount = Depends(get_current_patient_account), db: Session = Depends(get_db)):
    from datetime import timedelta

    patient_ids = _owned_patient_ids(account)
    if not patient_ids:
        return DashboardStatsOut(profile_count=0, consultation_count=0, visit_count_total=0, visit_count_last_30_days=0)

    consultation_count = db.query(Consultation).filter(
        Consultation.patient_id.in_(patient_ids), Consultation.is_voided == False  # noqa: E712
    ).count()
    visit_count_total = db.query(Checkin).filter(Checkin.patient_id.in_(patient_ids)).count()

    thirty_days_ago = now_ist_naive().date() - timedelta(days=30)
    visit_count_30d = db.query(Checkin).filter(
        Checkin.patient_id.in_(patient_ids), Checkin.visit_date >= thirty_days_ago
    ).count()

    return DashboardStatsOut(
        profile_count=len(patient_ids),
        consultation_count=consultation_count,
        visit_count_total=visit_count_total,
        visit_count_last_30_days=visit_count_30d,
    )


@router.get("/profiles", response_model=list[ProfileSummaryOut])
def list_profiles(account: PatientAccount = Depends(get_current_patient_account), db: Session = Depends(get_db)):
    out = []
    for link in account.profiles:
        patient = link.patient
        if not patient:
            continue
        hospital = db.query(Hospital).filter(Hospital.id == patient.hospital_id).first()
        visit_count = db.query(Checkin).filter(Checkin.patient_id == patient.id).count()
        out.append(ProfileSummaryOut(
            id=link.id, patient_id=patient.id, hospital_id=patient.hospital_id,
            hospital_name=hospital.name if hospital else "Unknown hospital",
            display_name=patient.name, relation=link.relation, visit_count=visit_count,
        ))
    return out


@router.get("/admissions", response_model=list[AdmissionSummaryOut])
def list_admissions(account: PatientAccount = Depends(get_current_patient_account), db: Session = Depends(get_db)):
    """Every hospital stay (current + past) across all linked profiles."""
    patient_ids = _owned_patient_ids(account)
    if not patient_ids:
        return []

    admissions = db.query(Admission).filter(
        Admission.patient_id.in_(patient_ids)
    ).order_by(Admission.admission_date.desc()).all()

    out = []
    for a in admissions:
        hospital = db.query(Hospital).filter(Hospital.id == a.hospital_id).first()
        patient = db.query(Patient).filter(Patient.id == a.patient_id).first()
        doctor = db.query(Doctor).filter(Doctor.id == a.admitting_doctor_id).first()
        invoice_total = None
        if a.status == "discharged" and a.discharge_invoice_id:
            invoice = db.query(Invoice).filter(Invoice.id == a.discharge_invoice_id).first()
            invoice_total = invoice.grand_total if invoice else None
        out.append(AdmissionSummaryOut(
            id=a.id,
            hospital_name=hospital.name if hospital else "Unknown hospital",
            patient_name=patient.name if patient else "Unknown",
            ward=a.ward,
            bed_number=a.bed_number,
            diagnosis=a.diagnosis,
            status=a.status,
            admitting_doctor_name=f"{doctor.title} {doctor.name}" if doctor else None,
            admission_date=a.admission_date.isoformat(),
            discharge_date=a.discharge_date.isoformat() if a.discharge_date else None,
            discharge_invoice_id=a.discharge_invoice_id if a.status == "discharged" else None,
            discharge_invoice_total=invoice_total,
        ))
    return out


@router.get("/admissions/{admission_id}/reports")
def admission_reports(admission_id: int, account: PatientAccount = Depends(get_current_patient_account), db: Session = Depends(get_db)):
    """Tests grouped into reports the same way they were ordered: everything
    submitted together in one "Order Test(s)" action (sharing an
    order_batch_id) is one report, regardless of how results trickle in.
    Tests ordered separately — even the same test, a different day — are
    separate reports. Legacy orders from before order_batch_id existed
    (null) each stand alone as their own single-test report. Names + status
    only, no price — money only ever surfaces via the discharge invoice."""
    patient_ids = _owned_patient_ids(account)
    admission = db.query(Admission).filter(Admission.id == admission_id, Admission.patient_id.in_(patient_ids)).first()
    if not admission:
        raise HTTPException(status_code=404, detail="Admission not found")

    orders = db.query(TestOrder).filter(
        TestOrder.admission_id == admission.id
    ).order_by(TestOrder.created_at.asc()).all()

    groups = {}
    order_index = []  # preserves first-seen order for stable output ordering
    for t in orders:
        key = t.order_batch_id or f"__single_{t.id}"
        if key not in groups:
            groups[key] = []
            order_index.append(key)
        groups[key].append(t)

    result = []
    for key in order_index:
        tests = groups[key]
        result.append({
            "batch_key": key,
            "order_date": min(t.created_at for t in tests).isoformat(),
            "tests": [{"id": t.id, "test_name": t.test_name, "status": t.status} for t in tests],
            "all_verified": all(t.status == "verified_released" for t in tests),
            "any_verified": any(t.status == "verified_released" for t in tests),
        })
    # Most recent report first — reads most naturally for a stay-in-progress.
    result.sort(key=lambda r: r["order_date"], reverse=True)
    return result


@router.get("/admissions/{admission_id}/reports/{batch_key}/pdf")
def download_admission_report_pdf(
    admission_id: int,
    batch_key: str,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    """One bundled PDF per report (batch) — same bundle-only rule as OPD
    visit reports. Only verified_released tests from this batch are
    included; if none are ready yet, 404."""
    patient_ids = _owned_patient_ids(account)
    admission = db.query(Admission).filter(Admission.id == admission_id, Admission.patient_id.in_(patient_ids)).first()
    if not admission:
        raise HTTPException(status_code=404, detail="Admission not found")

    all_in_admission = db.query(TestOrder).filter(TestOrder.admission_id == admission.id).all()
    if batch_key.startswith("__single_"):
        batch_orders = [t for t in all_in_admission if f"__single_{t.id}" == batch_key]
    else:
        batch_orders = [t for t in all_in_admission if t.order_batch_id == batch_key]

    orders = [t for t in batch_orders if t.status == "verified_released"]
    if not orders:
        raise HTTPException(status_code=404, detail="No completed test results in this report yet")

    patient = db.query(Patient).filter(Patient.id == admission.patient_id).first()
    hospital = db.query(Hospital).filter(Hospital.id == admission.hospital_id).first()
    ordering_doctor = db.query(Doctor).filter(Doctor.id == admission.admitting_doctor_id).first() if admission.admitting_doctor_id else None
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
                TestCatalogParameter.is_active == True  # noqa: E712
            ).order_by(TestCatalogParameter.display_order).all()
            rows = [{
                "name": p.name, "unit": p.unit or "",
                "range": (p.reference_range_male if is_male else p.reference_range_female) or "",
                "value": result_data.get(p.name, "")
            } for p in params if result_data.get(p.name)]
        else:
            range_str = (catalog_item.reference_range_male if is_male else catalog_item.reference_range_female) if catalog_item else ""
            unit = catalog_item.unit if catalog_item else ""
            rows = [{"name": order.test_name, "unit": unit or "", "range": range_str or "", "value": result_data.get("value", "")}]

        tests_payload.append({"test_name": order.test_name, "rows": rows, "notes": result_data.get("notes", "")})

    filepath = generate_combined_test_report_pdf(
        order_id_key=f"admission_{admission_id}_{batch_key}", tests_payload=tests_payload,
        patient=patient, ordering_doctor=ordering_doctor, lab_staff=lab_staff, hospital=hospital
    )
    return FileResponse(filepath, media_type="application/pdf", filename=f"test_report_admission_{admission_id}.pdf")


@router.get("/admissions/{admission_id}/medications")
def admission_medications(admission_id: int, account: PatientAccount = Depends(get_current_patient_account), db: Session = Depends(get_db)):
    patient_ids = _owned_patient_ids(account)
    admission = db.query(Admission).filter(Admission.id == admission_id, Admission.patient_id.in_(patient_ids)).first()
    if not admission:
        raise HTTPException(status_code=404, detail="Admission not found")
    orders = db.query(AdmissionMedicationOrder).filter(
        AdmissionMedicationOrder.admission_id == admission.id
    ).order_by(AdmissionMedicationOrder.created_at.desc()).all()
    return [{
        "id": o.id, "medicine_name": o.medicine_name, "dosage": o.dosage,
        "route": o.route, "frequency": o.frequency_note,
        "is_active": o.is_active, "sourced_outside": o.sourced_outside,
        "started_at": o.created_at.isoformat() if o.created_at else None,
    } for o in orders]

@router.patch("/admissions/{admission_id}/medications/{order_id}/sourced-outside")
def set_sourced_outside(admission_id: int, order_id: int, body: dict, account: PatientAccount = Depends(get_current_patient_account), db: Session = Depends(get_db)):
    patient_ids = _owned_patient_ids(account)
    admission = db.query(Admission).filter(Admission.id == admission_id, Admission.patient_id.in_(patient_ids)).first()
    if not admission:
        raise HTTPException(status_code=404, detail="Admission not found")
    order = db.query(AdmissionMedicationOrder).filter(AdmissionMedicationOrder.id == order_id, AdmissionMedicationOrder.admission_id == admission.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Medication order not found")
    order.sourced_outside = bool(body.get("sourced_outside", False))
    db.commit()
    return {"sourced_outside": order.sourced_outside}


@router.get("/visits", response_model=list[VisitOut])
def list_all_visits(account: PatientAccount = Depends(get_current_patient_account), db: Session = Depends(get_db)):
    """Flat list of visits across every linked profile — used for the
    searchable/filterable Health Records view."""
    out = []
    for link in account.profiles:
        patient = link.patient
        if not patient:
            continue
        hospital = db.query(Hospital).filter(Hospital.id == patient.hospital_id).first()
        checkins = db.query(Checkin).filter(Checkin.patient_id == patient.id).order_by(Checkin.visit_date.desc()).all()
        for c in checkins:
            h = db.query(Hospital).filter(Hospital.id == c.hospital_id).first() or hospital
            doctor = db.query(Doctor).filter(Doctor.id == c.doctor_id).first()
            consultation = db.query(Consultation).filter(
                Consultation.token_number == c.token_number, Consultation.is_voided == False  # noqa: E712
            ).first()
            test_count = db.query(TestOrder).filter(TestOrder.consultation_id == consultation.id).count() if consultation else 0
            out.append(VisitOut(
                checkin_id=c.id, token_number=c.token_number,
                visit_date=c.visit_date.isoformat(),
                hospital_name=h.name if h else "Unknown hospital",
                doctor_name=f"{doctor.title} {doctor.name}" if doctor else None,
                patient_name=patient.name,
                has_prescription=consultation is not None,
                has_invoice=c.invoice_id is not None,
                test_count=test_count,
            ))
    out.sort(key=lambda v: v.visit_date, reverse=True)
    return out


@router.get("/profiles/{profile_link_id}/visits", response_model=list[VisitOut])
def list_visits(
    profile_link_id: int,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    link = next((p for p in account.profiles if p.id == profile_link_id and p.relation != "pending_confirmation"), None)
    if not link or not link.patient:
        raise HTTPException(status_code=404, detail="Profile not found — confirm it under your profile menu first if it's a recently linked record")

    patient = link.patient
    checkins = (
        db.query(Checkin)
        .filter(Checkin.patient_id == patient.id)
        .order_by(Checkin.visit_date.desc(), Checkin.created_at.desc())
        .all()
    )

    out = []
    for c in checkins:
        hospital = db.query(Hospital).filter(Hospital.id == c.hospital_id).first()
        doctor = db.query(Doctor).filter(Doctor.id == c.doctor_id).first()
        consultation = db.query(Consultation).filter(
            Consultation.token_number == c.token_number, Consultation.is_voided == False  # noqa: E712
        ).first()
        test_count = db.query(TestOrder).filter(TestOrder.consultation_id == consultation.id).count() if consultation else 0

        out.append(VisitOut(
            checkin_id=c.id, token_number=c.token_number,
            visit_date=c.visit_date.isoformat(),
            hospital_name=hospital.name if hospital else "Unknown hospital",
            doctor_name=f"{doctor.title} {doctor.name}" if doctor else None,
            patient_name=patient.name,
            has_prescription=consultation is not None,
            has_invoice=c.invoice_id is not None,
            test_count=test_count,
        ))
    return out


@router.get("/visits/{checkin_id}", response_model=VisitDetailOut)
def get_visit_detail(
    checkin_id: int,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    checkin = db.query(Checkin).filter(Checkin.id == checkin_id).first()
    if not checkin or checkin.patient_id not in _owned_patient_ids(account):
        raise HTTPException(status_code=404, detail="Visit not found")

    patient = db.query(Patient).filter(Patient.id == checkin.patient_id).first()
    hospital = db.query(Hospital).filter(Hospital.id == checkin.hospital_id).first()
    doctor = db.query(Doctor).filter(Doctor.id == checkin.doctor_id).first()
    consultation = db.query(Consultation).filter(
        Consultation.token_number == checkin.token_number, Consultation.is_voided == False  # noqa: E712
    ).first()

    tests = []
    if consultation:
        tests = [
            VisitTestOut(id=t.id, test_name=t.test_name, status=t.status)
            for t in db.query(TestOrder).filter(TestOrder.consultation_id == consultation.id).all()
        ]

    invoice = db.query(Invoice).filter(Invoice.id == checkin.invoice_id).first() if checkin.invoice_id else None

    from app.models.feedback import VisitFeedback
    feedback_given = db.query(VisitFeedback).filter(VisitFeedback.checkin_id == checkin.id).first() is not None

    return VisitDetailOut(
        checkin_id=checkin.id, token_number=checkin.token_number,
        visit_date=checkin.visit_date.isoformat(),
        hospital_name=hospital.name if hospital else "Unknown hospital",
        doctor_name=f"{doctor.title} {doctor.name}" if doctor else None,
        patient_name=patient.name if patient else "Unknown",
        consultation_id=consultation.id if consultation else None,
        diagnosis=consultation.diagnosis if consultation else None,
        invoice_id=invoice.id if invoice else None,
        invoice_total=invoice.grand_total if invoice else None,
        tests=tests,
        feedback_given=feedback_given,
    )


@router.post("/visits/{checkin_id}/feedback")
def submit_visit_feedback(
    checkin_id: int,
    body: VisitFeedbackIn,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    if body.rating < 1 or body.rating > 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

    checkin = db.query(Checkin).filter(Checkin.id == checkin_id).first()
    if not checkin or checkin.patient_id not in _owned_patient_ids(account):
        raise HTTPException(status_code=404, detail="Visit not found")
    if not checkin.is_finalized:
        raise HTTPException(status_code=400, detail="Feedback is only available once the visit is complete")

    from app.models.feedback import VisitFeedback
    existing = db.query(VisitFeedback).filter(VisitFeedback.checkin_id == checkin_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Feedback already submitted for this visit")

    db.add(VisitFeedback(
        checkin_id=checkin_id, patient_id=checkin.patient_id, hospital_id=checkin.hospital_id,
        rating=body.rating, comment=body.comment,
    ))
    db.commit()
    return {"message": "Thanks for the feedback"}


@router.post("/suggestion")
def submit_suggestion(
    body: PortalSuggestionIn,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Please enter a suggestion")

    from app.models.feedback import PortalSuggestion
    db.add(PortalSuggestion(account_id=account.id, hospital_id=body.hospital_id, message=body.message.strip()))
    db.commit()
    return {"message": "Thanks for the suggestion"}


@router.get("/hospital-feedback")
def list_hospital_feedback(
    current_doctor=Depends(get_current_doctor),
    db: Session = Depends(get_db),
):
    """Hospital-facing view of patient visit feedback — admin/sub_admin only."""
    if current_doctor.role.value not in ("admin", "sub_admin"):
        raise HTTPException(status_code=403, detail="Not authorized")

    from app.models.feedback import VisitFeedback
    rows = db.query(VisitFeedback).filter(
        VisitFeedback.hospital_id == current_doctor.hospital_id
    ).order_by(VisitFeedback.created_at.desc()).limit(200).all()

    result = []
    for r in rows:
        patient = db.query(Patient).filter(Patient.id == r.patient_id).first()
        result.append({
            "id": r.id, "patient_name": patient.name if patient else "Unknown",
            "rating": r.rating, "comment": r.comment,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return result


@router.get("/consultations/{consultation_id}/tests/report")
def download_consultation_test_report(
    consultation_id: int,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    """One bundled PDF covering every completed test ordered on this visit —
    there is deliberately no per-test download anywhere on the site (site rule:
    bundle-only). Incomplete tests are left out; if none are complete yet, 404."""
    consultation = db.query(Consultation).filter(Consultation.id == consultation_id).first()
    if not consultation:
        raise HTTPException(status_code=404, detail="Visit not found")
    patient = db.query(Patient).filter(Patient.id == consultation.patient_id).first()
    if not patient or patient.id not in _owned_patient_ids(account):
        raise HTTPException(status_code=404, detail="Visit not found")

    orders = db.query(TestOrder).filter(
        TestOrder.consultation_id == consultation_id, TestOrder.status == "verified_released"
    ).all()
    if not orders:
        raise HTTPException(status_code=404, detail="No completed test results for this visit yet")

    hospital = db.query(Hospital).filter(Hospital.id == patient.hospital_id).first()
    ordering_doctor = db.query(Doctor).filter(Doctor.id == consultation.doctor_id).first()
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
                TestCatalogParameter.is_active == True  # noqa: E712
            ).order_by(TestCatalogParameter.display_order).all()
            rows = [{
                "name": p.name, "unit": p.unit or "",
                "range": (p.reference_range_male if is_male else p.reference_range_female) or "",
                "value": result_data.get(p.name, "")
            } for p in params if result_data.get(p.name)]  # untested subtests excluded, not just blanked
        else:
            range_str = (catalog_item.reference_range_male if is_male else catalog_item.reference_range_female) if catalog_item else ""
            unit = catalog_item.unit if catalog_item else ""
            rows = [{"name": order.test_name, "unit": unit or "", "range": range_str or "", "value": result_data.get("value", "")}]

        tests_payload.append({"test_name": order.test_name, "rows": rows, "notes": result_data.get("notes", "")})

    filepath = generate_combined_test_report_pdf(
        order_id_key=f"portal_{consultation_id}", tests_payload=tests_payload,
        patient=patient, ordering_doctor=ordering_doctor, lab_staff=lab_staff, hospital=hospital
    )
    return FileResponse(filepath, media_type="application/pdf", filename=f"test_report_{consultation.token_number}.pdf")


@router.get("/prescriptions/{consultation_id}/pdf")
def download_prescription_pdf(
    consultation_id: int,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    consultation = db.query(Consultation).filter(
        Consultation.id == consultation_id, Consultation.is_voided == False  # noqa: E712
    ).first()
    if not consultation or consultation.patient_id not in _owned_patient_ids(account):
        raise HTTPException(status_code=404, detail="Prescription not found")

    patient = db.query(Patient).filter(Patient.id == consultation.patient_id).first()
    prescribing_doctor = db.query(Doctor).filter(Doctor.id == consultation.doctor_id).first()

    pdf_path = generate_prescription_pdf(
        prescribing_doctor, patient, consultation,
        consultation.token_number, consultation.verify_hash or ""
    )
    return FileResponse(
        pdf_path, media_type="application/pdf",
        filename=f"{consultation.token_number}.pdf",
        headers={"Cache-Control": "no-store"}
    )


@router.get("/invoices/{invoice_id}/pdf")
def download_invoice_pdf(
    invoice_id: int,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice or invoice.patient_id not in _owned_patient_ids(account):
        raise HTTPException(status_code=404, detail="Invoice not found")

    patient = db.query(Patient).filter(Patient.id == invoice.patient_id).first()
    hospital = db.query(Hospital).filter(Hospital.id == invoice.hospital_id).first()
    import json as _json
    items = _json.loads(invoice.items_json)

    checkin = db.query(Checkin).filter(Checkin.id == invoice.checkin_id).first()
    consulting_doctor = db.query(Doctor).filter(Doctor.id == checkin.doctor_id).first() if checkin else None

    pdf_path = generate_invoice_pdf(invoice.id, hospital, items, invoice.grand_total, patient, consulting_doctor, receipt_number=invoice.receipt_number)
    return FileResponse(
        pdf_path, media_type="application/pdf",
        filename=f"invoice_{invoice_id}.pdf",
        headers={"Cache-Control": "no-store"}
    )