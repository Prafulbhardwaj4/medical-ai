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
from app.schemas.portal import DashboardStatsOut, ProfileSummaryOut, VisitOut, VisitDetailOut, VisitTestOut
from app.utils.portal_auth import get_current_patient_account
from app.services.pdf_service import generate_prescription_pdf, generate_invoice_pdf

router = APIRouter(prefix="/portal/dashboard", tags=["portal-dashboard"])


def _owned_patient_ids(account: PatientAccount) -> set:
    return {link.patient_id for link in account.profiles}


@router.get("/stats", response_model=DashboardStatsOut)
def get_stats(account: PatientAccount = Depends(get_current_patient_account), db: Session = Depends(get_db)):
    patient_ids = _owned_patient_ids(account)
    if not patient_ids:
        return DashboardStatsOut(profile_count=0, consultation_count=0, visit_count=0)

    consultation_count = db.query(Consultation).filter(
        Consultation.patient_id.in_(patient_ids), Consultation.is_voided == False  # noqa: E712
    ).count()
    visit_count = db.query(Checkin).filter(Checkin.patient_id.in_(patient_ids)).count()

    return DashboardStatsOut(
        profile_count=len(account.profiles),
        consultation_count=consultation_count,
        visit_count=visit_count,
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


@router.get("/profiles/{profile_link_id}/visits", response_model=list[VisitOut])
def list_visits(
    profile_link_id: int,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    link = next((p for p in account.profiles if p.id == profile_link_id), None)
    if not link or not link.patient:
        raise HTTPException(status_code=404, detail="Profile not found")

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
    )


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

    pdf_path = generate_invoice_pdf(invoice.id, hospital, items, invoice.grand_total, patient, consulting_doctor)
    return FileResponse(
        pdf_path, media_type="application/pdf",
        filename=f"invoice_{invoice_id}.pdf",
        headers={"Cache-Control": "no-store"}
    )