import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.portal import PatientAccount, PatientProfileLink
from app.models.patient import Patient
from app.models.consultation import Consultation
from app.models.test_order import TestOrder
from app.models.invoice import Invoice
from app.models.hospital import Hospital
from app.models.doctor import Doctor
from app.models.checkin import Checkin
from app.schemas.portal import DashboardOut, ProfileOut
from app.utils.portal_auth import get_current_patient_account
from app.services.pdf_service import generate_prescription_pdf, generate_invoice_pdf

router = APIRouter(prefix="/portal/dashboard", tags=["portal-dashboard"])


def _owned_patient_ids(account: PatientAccount) -> set:
    return {link.patient_id for link in account.profiles}


@router.get("", response_model=DashboardOut)
def get_dashboard(
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    profiles = []
    records = {}

    for link in account.profiles:
        patient = link.patient
        hospital = db.query(Hospital).filter(Hospital.id == patient.hospital_id).first()

        profiles.append(ProfileOut(
            id=link.id,
            patient_id=patient.id,
            hospital_id=patient.hospital_id,
            hospital_name=hospital.name if hospital else "Unknown",
            display_name=patient.name,
            relation=link.relation,
            linked_at=link.linked_at,
        ))

        consultations = db.query(Consultation).filter(Consultation.patient_id == patient.id).all()
        tests = db.query(TestOrder).filter(TestOrder.patient_id == patient.id).all()
        invoices = db.query(Invoice).filter(Invoice.patient_id == patient.id).all()

        records[link.id] = {
            "prescriptions": [
                {
                    "id": c.id,
                    "token_number": c.token_number,
                    "diagnosis": c.diagnosis,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "pdf_path": c.pdf_path,
                }
                for c in consultations if c.token_number and not c.is_voided
            ],
            "tests": [
                {"id": t.id, "test_name": t.test_name, "status": t.status,
                 "created_at": t.created_at.isoformat() if t.created_at else None}
                for t in tests
            ],
            "invoices": [
                {"id": i.id, "grand_total": i.grand_total,
                 "generated_at": i.generated_at.isoformat() if i.generated_at else None}
                for i in invoices
            ],
        }

    return DashboardOut(profiles=profiles, records=records)


@router.get("/prescriptions/{consultation_id}/pdf")
def download_prescription_pdf(
    consultation_id: int,
    account: PatientAccount = Depends(get_current_patient_account),
    db: Session = Depends(get_db),
):
    consultation = db.query(Consultation).filter(
        Consultation.id == consultation_id,
        Consultation.is_voided == False  # noqa: E712
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
    items = json.loads(invoice.items_json)

    checkin = db.query(Checkin).filter(Checkin.id == invoice.checkin_id).first()
    consulting_doctor = db.query(Doctor).filter(Doctor.id == checkin.doctor_id).first() if checkin else None

    pdf_path = generate_invoice_pdf(invoice.id, hospital, items, invoice.grand_total, patient, consulting_doctor)
    return FileResponse(
        pdf_path, media_type="application/pdf",
        filename=f"invoice_{invoice_id}.pdf",
        headers={"Cache-Control": "no-store"}
    )