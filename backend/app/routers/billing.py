from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from datetime import datetime
import json, os

from app.database import get_db
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.hospital import Hospital
from app.models.checkin import Checkin
from app.models.consultation import Consultation
from app.models.test_order import TestOrder
from app.models.medicine_order import MedicineOrder
from app.models.invoice import Invoice
from app.utils.auth import get_current_doctor
from app.utils.audit import log_action
from app.services.pdf_service import generate_invoice_pdf

router = APIRouter(prefix="/billing", tags=["billing"])


def require_billing_staff(current_doctor: Doctor):
    if current_doctor.role.value not in ["receptionist", "pharmacy", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")


def gather_invoice_items(db: Session, checkin: Checkin):
    items = []

    if checkin.consultation_fee and checkin.is_paid:
        items.append({
            "type": "consultation",
            "name": "Consultation Fee",
            "qty": 1,
            "unit_price": checkin.consultation_fee,
            "line_total": checkin.consultation_fee
        })

    consultation_ids = [
        c.id for c in db.query(Consultation).filter(
            Consultation.patient_id == checkin.patient_id
        ).all()
    ]

    test_orders = db.query(TestOrder).filter(
        TestOrder.patient_id == checkin.patient_id,
        TestOrder.hospital_id == checkin.hospital_id,
        TestOrder.status.in_(["paid", "sample_collected", "processing", "completed"]),
        TestOrder.consultation_id.in_(consultation_ids) if consultation_ids else False
    ).all()
    for t in test_orders:
        items.append({
            "type": "test",
            "name": t.test_name,
            "qty": 1,
            "unit_price": t.price,
            "line_total": t.price
        })

    medicine_orders = db.query(MedicineOrder).filter(
        MedicineOrder.patient_id == checkin.patient_id,
        MedicineOrder.hospital_id == checkin.hospital_id,
        MedicineOrder.status.in_(["paid", "dispensed"]),
        MedicineOrder.consultation_id.in_(consultation_ids) if consultation_ids else False
    ).all()
    for m in medicine_orders:
        items.append({
            "type": "medicine",
            "name": f"{m.medicine_name}{' (' + m.brand_name + ')' if m.brand_name else ''}",
            "qty": m.quantity or 1,
            "unit_price": m.unit_price or 0,
            "line_total": (m.unit_price or 0) * (m.quantity or 1)
        })

    return items


@router.post("/checkins/{checkin_id}/finalize-invoice")
def finalize_invoice(
    checkin_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_billing_staff(current_doctor)

    checkin = db.query(Checkin).filter(
        Checkin.id == checkin_id,
        Checkin.hospital_id == current_doctor.hospital_id
    ).first()
    if not checkin:
        raise HTTPException(status_code=404, detail="Visit not found")

    if checkin.is_finalized and checkin.invoice_id:
        invoice = db.query(Invoice).filter(Invoice.id == checkin.invoice_id).first()
        return serialize_invoice(invoice)

    items = gather_invoice_items(db, checkin)
    if not items:
        raise HTTPException(status_code=400, detail="Nothing paid yet for this visit")

    grand_total = sum(i["line_total"] for i in items)

    invoice = Invoice(
        checkin_id=checkin.id,
        patient_id=checkin.patient_id,
        hospital_id=current_doctor.hospital_id,
        items_json=json.dumps(items),
        grand_total=grand_total,
        generated_by=current_doctor.id,
        generated_from=current_doctor.role.value,
    )
    db.add(invoice)
    db.flush()

    patient = db.query(Patient).filter(Patient.id == checkin.patient_id).first()
    hospital = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()

    pdf_path = generate_invoice_pdf(invoice.id, hospital, items, grand_total, patient)
    invoice.pdf_path = pdf_path

    checkin.is_finalized = True
    checkin.invoice_id = invoice.id

    db.commit()
    db.refresh(invoice)

    log_action(
        db, current_doctor,
        action="invoice_generated",
        target_type="invoice",
        target_id=invoice.id,
        target_label=f"₹{grand_total} for checkin {checkin_id}",
        hospital_id=current_doctor.hospital_id
    )
    return serialize_invoice(invoice)


def serialize_invoice(invoice: Invoice):
    return {
        "id": invoice.id,
        "checkin_id": invoice.checkin_id,
        "items": json.loads(invoice.items_json),
        "grand_total": invoice.grand_total,
        "generated_from": invoice.generated_from,
        "generated_at": invoice.generated_at.isoformat() if invoice.generated_at else None
    }


@router.get("/checkins/{checkin_id}/invoice")
def get_invoice_for_checkin(
    checkin_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_billing_staff(current_doctor)

    checkin = db.query(Checkin).filter(
        Checkin.id == checkin_id,
        Checkin.hospital_id == current_doctor.hospital_id
    ).first()
    if not checkin or not checkin.invoice_id:
        raise HTTPException(status_code=404, detail="No invoice generated yet for this visit")

    invoice = db.query(Invoice).filter(Invoice.id == checkin.invoice_id).first()
    return serialize_invoice(invoice)


@router.get("/invoices/{invoice_id}/pdf")
def download_invoice_pdf(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_billing_staff(current_doctor)

    invoice = db.query(Invoice).filter(
        Invoice.id == invoice_id,
        Invoice.hospital_id == current_doctor.hospital_id
    ).first()
    if not invoice or not invoice.pdf_path or not os.path.exists(invoice.pdf_path):
        raise HTTPException(status_code=404, detail="Invoice PDF not found")

    return FileResponse(invoice.pdf_path, media_type="application/pdf", filename=f"invoice_{invoice_id}.pdf")


@router.get("/invoices")
def list_invoices(
    from_date: str = None,
    to_date: str = None,
    search: str = "",
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    query = db.query(Invoice).filter(Invoice.hospital_id == current_doctor.hospital_id)

    if from_date:
        query = query.filter(Invoice.generated_at >= datetime.fromisoformat(from_date))
    if to_date:
        query = query.filter(Invoice.generated_at <= datetime.fromisoformat(to_date + "T23:59:59"))

    invoices = query.order_by(Invoice.generated_at.desc()).limit(500).all()

    result = []
    for inv in invoices:
        patient = db.query(Patient).filter(Patient.id == inv.patient_id).first()
        checkin = db.query(Checkin).filter(Checkin.id == inv.checkin_id).first()
        if search and patient and search.lower() not in patient.name.lower() and (not checkin or search.lower() not in (checkin.token_number or "").lower()):
            continue
        result.append({
            "id": inv.id,
            "patient_name": patient.name if patient else "Unknown",
            "token_number": checkin.token_number if checkin else "—",
            "grand_total": inv.grand_total,
            "item_count": len(json.loads(inv.items_json)),
            "generated_from": inv.generated_from,
            "generated_at": inv.generated_at.isoformat() if inv.generated_at else None
        })
    return result


@router.get("/checkins/{checkin_id}/preview-slip")
def preview_slip(
    checkin_id: int,
    scope: str = "all",
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """View-only breakdown by scope (consultation/tests/medicines/all) — does NOT finalize or save anything.
    Used for 'give them the pieces separately' on difficult patients, without affecting the one-invoice-per-visit lock."""
    require_billing_staff(current_doctor)

    checkin = db.query(Checkin).filter(
        Checkin.id == checkin_id,
        Checkin.hospital_id == current_doctor.hospital_id
    ).first()
    if not checkin:
        raise HTTPException(status_code=404, detail="Visit not found")

    items = gather_invoice_items(db, checkin)
    if scope != "all":
        items = [i for i in items if i["type"] == scope.rstrip("s")]  # "tests" -> "test", "medicines" -> "medicine"

    return {
        "items": items,
        "total": sum(i["line_total"] for i in items)
    }