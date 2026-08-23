from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_
from datetime import datetime, timedelta
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
from app.models.opd_charge import OpdCharge
from app.models.hospital_medicine import HospitalMedicine
from app.models.admission import Admission, AdmissionCharge
from app.models.admission_deposit import AdmissionDeposit
from app.models.refund import Refund
from app.models.day_end_close import DayEndClose
from app.models.credit_debit_note import CreditDebitNote
from app.models.waiver_request import WaiverRequest
from app.schemas.billing import DayEndCloseIn, CreditDebitNoteIn, WaiverIn
from app.utils.gst import apply_gst
from app.utils.auth import get_current_doctor
from app.utils.audit import log_action
from app.services.pdf_service import generate_invoice_pdf
from app.utils.timezone import ist_today, ist_day_bounds, ist_date, now_ist_naive
from app.utils.receipts import next_receipt_number, next_note_number

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
            Consultation.patient_id == checkin.patient_id,
            Consultation.is_voided == False,
            or_(
                Consultation.token_number == checkin.token_number,
                Consultation.token_number.like(f"{checkin.token_number}-%")
            )
        ).all()
    ]

    test_orders = db.query(TestOrder).filter(
        TestOrder.patient_id == checkin.patient_id,
        TestOrder.hospital_id == checkin.hospital_id,
        TestOrder.status.in_(["paid", "sample_collected", "processing", "result_entered", "verified_released"]),
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
        billed = m.billed_quantity if m.billed_quantity is not None else m.quantity
        medicine_gst_percent = None
        medicine_hsn_code = None
        if m.catalog_medicine_id:
            hm = db.query(HospitalMedicine).filter(HospitalMedicine.id == m.catalog_medicine_id).first()
            medicine_gst_percent = hm.gst_percent if hm else None
            medicine_hsn_code = hm.hsn_code if hm else None
        items.append({
            "type": "medicine",
            "name": f"{m.medicine_name}{' (' + m.brand_name + ')' if m.brand_name else ''}",
            "qty": billed or 1,
            "unit_price": m.unit_price or 0,
            "line_total": (m.unit_price or 0) * (billed or 1),
            "_medicine_gst_percent": medicine_gst_percent,
            "_medicine_hsn_code": medicine_hsn_code
        })

    opd_charges = db.query(OpdCharge).filter(
        OpdCharge.checkin_id == checkin.id,
        OpdCharge.status == "paid"
    ).all()
    for oc in opd_charges:
        items.append({
            "type": "charge",
            "name": oc.description,
            "qty": oc.quantity,
            "unit_price": oc.amount,
            "line_total": oc.amount * oc.quantity
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

    items = gather_invoice_items(db, checkin)
    if not items:
        raise HTTPException(status_code=400, detail="Nothing paid yet for this visit")

    patient = db.query(Patient).filter(Patient.id == checkin.patient_id).first()
    hospital = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()
    consulting_doctor = db.query(Doctor).filter(Doctor.id == checkin.doctor_id).first()

    items, subtotal, gst_total, grand_total = apply_gst(items, hospital)

    if checkin.is_finalized and checkin.invoice_id:
        # Combined bill regenerates in place when something new was paid later in the
        # same visit (e.g. a test paid after the first invoice was generated) — same
        # invoice row, same receipt number, updated items/total/PDF.
        invoice = db.query(Invoice).filter(Invoice.id == checkin.invoice_id).first()
        invoice.items_json = json.dumps(items)
        invoice.grand_total = grand_total
        invoice.subtotal = subtotal
        invoice.gst_total = gst_total
        invoice.generated_by = current_doctor.id
        invoice.generated_from = current_doctor.role.value
        if not invoice.place_of_supply:
            invoice.place_of_supply = hospital.state
        pdf_path = generate_invoice_pdf(invoice.id, hospital, items, grand_total, patient, consulting_doctor, receipt_number=invoice.receipt_number, place_of_supply=invoice.place_of_supply)
        invoice.pdf_path = pdf_path
        db.commit()
        db.refresh(invoice)
        log_action(
            db, current_doctor,
            action="invoice_regenerated",
            target_type="invoice",
            target_id=invoice.id,
            target_label=f"Rs.{grand_total:.2f} for checkin {checkin_id}",
            hospital_id=current_doctor.hospital_id
        )
        return serialize_invoice(invoice)

    invoice = Invoice(
        checkin_id=checkin.id,
        patient_id=checkin.patient_id,
        hospital_id=current_doctor.hospital_id,
        items_json=json.dumps(items),
        grand_total=grand_total,
        subtotal=subtotal,
        gst_total=gst_total,
        generated_by=current_doctor.id,
        generated_from=current_doctor.role.value,
        receipt_number=next_receipt_number(db, hospital),
        place_of_supply=hospital.state,
    )
    db.add(invoice)
    db.flush()

    pdf_path = generate_invoice_pdf(invoice.id, hospital, items, grand_total, patient, consulting_doctor, receipt_number=invoice.receipt_number, place_of_supply=invoice.place_of_supply)
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
        target_label=f"Rs.{grand_total:.2f} for checkin {checkin_id}",
        hospital_id=current_doctor.hospital_id
    )
    return serialize_invoice(invoice)


def serialize_invoice(invoice: Invoice):
    return {
        "id": invoice.id,
        "checkin_id": invoice.checkin_id,
        "receipt_number": invoice.receipt_number,
        "items": json.loads(invoice.items_json),
        "subtotal": invoice.subtotal,
        "gst_total": invoice.gst_total,
        "grand_total": invoice.grand_total,
        "generated_from": invoice.generated_from,
        "place_of_supply": invoice.place_of_supply,
        # Reserved for e-invoicing — always null until IRP integration exists.
        "irn": invoice.irn,
        "einvoice_status": invoice.einvoice_status,
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


@router.get("/invoices/patient/{patient_id}")
def list_patient_invoices(
    patient_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Lightweight invoice list for a single patient — used by the refund
    flow and the credit/debit note UI to pick which invoice a correction
    applies to. Open to any billing-facing role, unlike /invoices (which is
    the admin-only revenue listing)."""
    require_billing_staff(current_doctor)
    invoices = db.query(Invoice).filter(
        Invoice.patient_id == patient_id,
        Invoice.hospital_id == current_doctor.hospital_id
    ).order_by(Invoice.generated_at.desc()).limit(50).all()
    return [{
        "id": inv.id,
        "receipt_number": inv.receipt_number,
        "grand_total": inv.grand_total,
        "generated_at": inv.generated_at.isoformat() if inv.generated_at else None
    } for inv in invoices]


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
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    patient = db.query(Patient).filter(Patient.id == invoice.patient_id).first()
    hospital = db.query(Hospital).filter(Hospital.id == invoice.hospital_id).first()
    items = json.loads(invoice.items_json)

    checkin_for_doctor = db.query(Checkin).filter(Checkin.id == invoice.checkin_id).first()
    consulting_doctor = db.query(Doctor).filter(Doctor.id == checkin_for_doctor.doctor_id).first() if checkin_for_doctor else None
    pdf_path = generate_invoice_pdf(invoice.id, hospital, items, invoice.grand_total, patient, consulting_doctor, receipt_number=invoice.receipt_number)
    if invoice.pdf_path != pdf_path:
        invoice.pdf_path = pdf_path
        db.commit()

    return FileResponse(pdf_path, media_type="application/pdf", filename=f"invoice_{invoice_id}.pdf", headers={"Cache-Control": "no-store"})


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


def serialize_credit_debit_note(note):
    return {
        "id": note.id,
        "invoice_id": note.invoice_id,
        "note_type": note.note_type,
        "note_number": note.note_number,
        "invoice_number": note.invoice_number,
        "invoice_date": note.invoice_date.isoformat() if note.invoice_date else None,
        "amount": note.amount,
        "reason": note.reason,
        "refund_id": note.refund_id,
        "created_at": note.created_at.isoformat() if note.created_at else None,
    }


@router.post("/invoices/{invoice_id}/credit-debit-note")
def create_credit_debit_note(
    invoice_id: int,
    body: CreditDebitNoteIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Manual credit/debit note against an already-issued invoice. The
    original invoice is never edited directly — GST law requires a
    supplementary document instead."""
    require_billing_staff(current_doctor)
    if body.note_type not in ("credit", "debit"):
        raise HTTPException(status_code=400, detail="note_type must be 'credit' or 'debit'")
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero")
    if not body.reason.strip():
        raise HTTPException(status_code=400, detail="A reason is required")

    invoice = db.query(Invoice).filter(
        Invoice.id == invoice_id,
        Invoice.hospital_id == current_doctor.hospital_id
    ).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    hospital = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()
    note = CreditDebitNote(
        hospital_id=current_doctor.hospital_id,
        invoice_id=invoice.id,
        patient_id=invoice.patient_id,
        note_type=body.note_type,
        note_number=next_note_number(db, hospital, body.note_type),
        invoice_number=invoice.receipt_number,
        invoice_date=invoice.generated_at,
        amount=body.amount,
        reason=body.reason.strip(),
        created_by=current_doctor.id,
    )
    db.add(note)
    db.commit()
    db.refresh(note)

    patient = db.query(Patient).filter(Patient.id == invoice.patient_id).first()
    log_action(
        db, current_doctor,
        action=f"{body.note_type}_note_created",
        target_type="invoice",
        target_id=invoice.id,
        target_label=f"{patient.name} ({patient.patient_uid})" if patient else str(invoice.patient_id),
        details=f"{body.note_type.title()} note {note.note_number} — Rs.{body.amount:.2f} against invoice {invoice.receipt_number or invoice.id} — {body.reason}"
    )
    return serialize_credit_debit_note(note)


@router.get("/invoices/{invoice_id}/credit-debit-notes")
def list_credit_debit_notes(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_billing_staff(current_doctor)
    invoice = db.query(Invoice).filter(
        Invoice.id == invoice_id,
        Invoice.hospital_id == current_doctor.hospital_id
    ).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    notes = db.query(CreditDebitNote).filter(
        CreditDebitNote.invoice_id == invoice_id
    ).order_by(CreditDebitNote.created_at.desc()).all()
    return [serialize_credit_debit_note(n) for n in notes]


def _waiver_threshold(hospital, bill_total: float) -> float:
    """Auto-approve limit for a waiver on this bill — the larger of the
    hospital's flat rupee cap and its percent-of-bill cap. Either alone
    being enough is enough; no unlimited, unlogged discretion at any tier."""
    cap = hospital.waiver_auto_approve_cap or 0.0
    pct_cap = (hospital.waiver_auto_approve_percent or 0.0) / 100.0 * bill_total
    return max(cap, pct_cap)


def _apply_waiver_charge(db: Session, waiver: WaiverRequest, actor: Doctor):
    """Creates the actual negative bill line once a waiver is approved
    (immediately for auto-approved ones, or on manual admin approval)."""
    if waiver.admission_id:
        charge = AdmissionCharge(
            admission_id=waiver.admission_id, charge_type="other",
            description=f"Waiver/Discount — {waiver.reason}",
            amount=-abs(waiver.amount), quantity=1, added_by=actor.id, charged_at=now_ist_naive(),
        )
        db.add(charge)
        db.flush()
        waiver.charge_id = charge.id
    else:
        checkin = db.query(Checkin).filter(Checkin.id == waiver.checkin_id).first()
        charge = OpdCharge(
            checkin_id=waiver.checkin_id, patient_id=checkin.patient_id, hospital_id=waiver.hospital_id,
            description=f"Waiver/Discount — {waiver.reason}", amount=-abs(waiver.amount), quantity=1,
            added_by=actor.id, status="paid", paid_at=now_ist_naive(),
        )
        db.add(charge)
        db.flush()
        waiver.charge_id = charge.id


@router.post("/waivers")
def create_waiver(
    body: WaiverIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_billing_staff(current_doctor)
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero")
    if not body.reason.strip():
        raise HTTPException(status_code=400, detail="A reason is required")
    if not body.checkin_id and not body.admission_token:
        raise HTTPException(status_code=400, detail="Either checkin_id or admission_token is required")
    if body.checkin_id and body.admission_token:
        raise HTTPException(status_code=400, detail="Provide only one of checkin_id or admission_token")

    hospital = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()

    admission_internal_id = None
    if body.admission_token:
        from app.routers.admissions import _build_discharge_bill
        admission = db.query(Admission).filter(
            Admission.public_token == body.admission_token,
            Admission.hospital_id == current_doctor.hospital_id
        ).first()
        if not admission:
            raise HTTPException(status_code=404, detail="Admission not found")
        if admission.status != "admitted":
            raise HTTPException(status_code=400, detail="Cannot apply a waiver to a discharged admission")
        admission_internal_id = admission.id
        _, bill_total = _build_discharge_bill(db, admission)
    else:
        checkin = db.query(Checkin).filter(
            Checkin.id == body.checkin_id,
            Checkin.hospital_id == current_doctor.hospital_id
        ).first()
        if not checkin:
            raise HTTPException(status_code=404, detail="Visit not found")
        items = gather_invoice_items(db, checkin)
        bill_total = sum(i["line_total"] for i in items)

    if body.amount > bill_total:
        raise HTTPException(status_code=400, detail="Waiver amount cannot exceed the current bill total")

    threshold = _waiver_threshold(hospital, bill_total)
    waiver = WaiverRequest(
        hospital_id=current_doctor.hospital_id, checkin_id=body.checkin_id, admission_id=admission_internal_id,
        amount=body.amount, reason=body.reason.strip(), requested_by=current_doctor.id,
    )

    if body.amount <= threshold:
        waiver.status = "approved"
        waiver.resolved_by = current_doctor.id
        waiver.resolved_at = now_ist_naive()
        db.add(waiver)
        db.flush()
        _apply_waiver_charge(db, waiver, current_doctor)
        db.commit()
        log_action(db, current_doctor, action="waiver_applied", target_type=("admission" if admission_internal_id else "checkin"),
                   target_id=admission_internal_id or body.checkin_id, target_label=f"Rs.{body.amount:.2f} waiver", details=waiver.reason)
        return {"message": "Waiver applied", "status": "approved"}
    else:
        waiver.status = "pending_approval"
        db.add(waiver)
        db.commit()
        return {"message": "Waiver exceeds the auto-approve limit — sent for admin approval", "status": "pending_approval", "id": waiver.id}


@router.get("/waivers/pending")
def list_pending_waivers(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    waivers = db.query(WaiverRequest).filter(
        WaiverRequest.hospital_id == current_doctor.hospital_id,
        WaiverRequest.status == "pending_approval"
    ).order_by(WaiverRequest.requested_at.desc()).all()

    result = []
    for w in waivers:
        requester = db.query(Doctor).filter(Doctor.id == w.requested_by).first()
        if w.admission_id:
            adm = db.query(Admission).filter(Admission.id == w.admission_id).first()
            p = db.query(Patient).filter(Patient.id == adm.patient_id).first() if adm else None
            label = f"{p.name} ({p.patient_uid}) — IPD" if p else "IPD admission"
        else:
            c = db.query(Checkin).filter(Checkin.id == w.checkin_id).first()
            p = db.query(Patient).filter(Patient.id == c.patient_id).first() if c else None
            label = f"{p.name} ({p.patient_uid}) — OPD" if p else "OPD visit"
        result.append({
            "id": w.id, "amount": w.amount, "reason": w.reason, "label": label,
            "requested_by": f"{requester.title} {requester.name}" if requester else "—",
            "requested_at": w.requested_at.isoformat() if w.requested_at else None,
        })
    return result


@router.patch("/waivers/{waiver_id}/approve")
def approve_waiver(
    waiver_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    waiver = db.query(WaiverRequest).filter(
        WaiverRequest.id == waiver_id,
        WaiverRequest.hospital_id == current_doctor.hospital_id
    ).first()
    if not waiver:
        raise HTTPException(status_code=404, detail="Waiver request not found")
    if waiver.status != "pending_approval":
        raise HTTPException(status_code=400, detail="Only a pending waiver can be approved")
    waiver.status = "approved"
    waiver.resolved_by = current_doctor.id
    waiver.resolved_at = now_ist_naive()
    _apply_waiver_charge(db, waiver, current_doctor)
    db.commit()
    log_action(db, current_doctor, action="waiver_approved", target_type=("admission" if waiver.admission_id else "checkin"),
               target_id=waiver.admission_id or waiver.checkin_id, target_label=f"Rs.{waiver.amount:.2f} waiver", details=waiver.reason)
    return {"message": "Waiver approved and applied"}


@router.patch("/waivers/{waiver_id}/reject")
def reject_waiver(
    waiver_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    waiver = db.query(WaiverRequest).filter(
        WaiverRequest.id == waiver_id,
        WaiverRequest.hospital_id == current_doctor.hospital_id
    ).first()
    if not waiver:
        raise HTTPException(status_code=404, detail="Waiver request not found")
    if waiver.status != "pending_approval":
        raise HTTPException(status_code=400, detail="Only a pending waiver can be rejected")
    waiver.status = "rejected"
    waiver.resolved_by = current_doctor.id
    waiver.resolved_at = now_ist_naive()
    db.commit()
    return {"message": "Waiver rejected"}


# Revenue History (admin) — aggregate totals, not individual invoices (that's /invoices above).
# Deliberately bounded (3 months daily / 18 months monthly) rather than "since hospital
# creation": covers every real use an admin has (this week, month-over-month, year-over-year
# comparison) while keeping the query fast regardless of how long a hospital has been running.
# Computed live from Invoice rows each call, no rollup table — fine at real single-hospital
# invoice volumes, and each hospital's query only ever touches its own bounded window, so this
# doesn't get slower as more hospitals use the platform. Revisit only if one specific hospital's
# window genuinely gets big enough to matter, not preemptively.
MAX_DAILY_RANGE_DAYS = 548         # ~18 months, matches MAX_MONTHLY_RANGE_MONTHS
MAX_MONTHLY_RANGE_MONTHS = 18

def _clamp_daily_range(from_date: str, to_date: str):
    today = ist_today()
    earliest = today - timedelta(days=MAX_DAILY_RANGE_DAYS)
    to_d = datetime.fromisoformat(to_date).date() if to_date else today
    from_d = datetime.fromisoformat(from_date).date() if from_date else earliest
    to_d = min(to_d, today)
    from_d = max(from_d, earliest)
    if from_d > to_d:
        from_d = to_d
    return from_d, to_d

@router.get("/revenue-history/daily")
def revenue_history_daily(
    from_date: str = None,
    to_date: str = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    from_d, to_d = _clamp_daily_range(from_date, to_date)
    range_start, _ = ist_day_bounds(from_d)
    _, range_end = ist_day_bounds(to_d)

    invoices = db.query(Invoice).filter(
        Invoice.hospital_id == current_doctor.hospital_id,
        Invoice.generated_at >= range_start,
        Invoice.generated_at < range_end
    ).all()

    buckets = {}
    for inv in invoices:
        d = ist_date(inv.generated_at)
        if d not in buckets:
            buckets[d] = {"total": 0.0, "invoice_count": 0}
        buckets[d]["total"] += inv.subtotal if inv.subtotal is not None else inv.grand_total  # pre-tax revenue; GST collected isn't hospital revenue
        buckets[d]["invoice_count"] += 1

    return {
        "from_date": from_d.isoformat(),
        "to_date": to_d.isoformat(),
        "days": [
            {"date": d.isoformat(), "total": round(v["total"], 2), "invoice_count": v["invoice_count"]}
            for d, v in sorted(buckets.items())
        ]
    }

def _clamp_monthly_range(from_month: str, to_month: str):
    today = ist_today()
    def month_start(y, m):
        return datetime(y, m, 1).date()
    def add_months(y, m, n):
        total = (y * 12 + (m - 1)) + n
        return total // 12, total % 12 + 1

    ey, em = add_months(today.year, today.month, -(MAX_MONTHLY_RANGE_MONTHS - 1))
    earliest = month_start(ey, em)
    latest = month_start(today.year, today.month)

    if to_month:
        ty, tm = [int(x) for x in to_month.split("-")]
        to_d = month_start(ty, tm)
    else:
        to_d = latest
    if from_month:
        fy, fm = [int(x) for x in from_month.split("-")]
        from_d = month_start(fy, fm)
    else:
        from_d = earliest

    to_d = min(to_d, latest)
    from_d = max(from_d, earliest)
    if from_d > to_d:
        from_d = to_d
    return from_d, to_d

@router.get("/revenue-history/monthly")
def revenue_history_monthly(
    from_month: str = None,   # "YYYY-MM"
    to_month: str = None,     # "YYYY-MM"
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    from_d, to_d = _clamp_monthly_range(from_month, to_month)
    range_start, _ = ist_day_bounds(from_d)
    to_next_y, to_next_m = (to_d.year + 1, 1) if to_d.month == 12 else (to_d.year, to_d.month + 1)
    range_end_ist = datetime(to_next_y, to_next_m, 1).date()
    _, range_end = ist_day_bounds(range_end_ist - timedelta(days=1))

    invoices = db.query(Invoice).filter(
        Invoice.hospital_id == current_doctor.hospital_id,
        Invoice.generated_at >= range_start,
        Invoice.generated_at < range_end
    ).all()

    buckets = {}
    for inv in invoices:
        d = ist_date(inv.generated_at)
        key = (d.year, d.month)
        if key not in buckets:
            buckets[key] = {"total": 0.0, "invoice_count": 0}
        buckets[key]["total"] += inv.subtotal if inv.subtotal is not None else inv.grand_total  # pre-tax revenue; GST collected isn't hospital revenue
        buckets[key]["invoice_count"] += 1

    return {
        "from_month": f"{from_d.year:04d}-{from_d.month:02d}",
        "to_month": f"{to_d.year:04d}-{to_d.month:02d}",
        "months": [
            {"month": f"{y:04d}-{m:02d}", "total": round(v["total"], 2), "invoice_count": v["invoice_count"]}
            for (y, m), v in sorted(buckets.items())
        ]
    }


def close_day_for_hospital(db: Session, hospital_id: int, d, closed_by: int = None, note: str = None):
    """Shared close-one-day logic — used both by the lazy per-request
    catch-up below and by the midnight scheduler in app/scheduler.py.
    closed_by is nullable: the scheduled midnight run has no logged-in staff
    member to attribute it to."""
    day_start, day_end = ist_day_bounds(d)
    has_activity = db.query(Checkin.id).filter(
        Checkin.hospital_id == hospital_id, Checkin.visit_date == d
    ).first()
    if not has_activity:
        return False  # nothing happened that day — nothing to close

    summary = _day_end_summary_core(db, hospital_id, d)
    totals = summary["system_totals"]
    db.add(DayEndClose(
        hospital_id=hospital_id,
        close_date=d,
        system_cash=totals.get("cash", 0), system_card=totals.get("card", 0), system_upi=totals.get("upi", 0),
        counted_cash=totals.get("cash", 0), counted_card=totals.get("card", 0), counted_upi=totals.get("upi", 0),
        notes=note or "Auto-closed by system — no manual count was entered before day rollover.",
        closed_by=closed_by,
    ))
    db.commit()
    return True


def auto_close_past_days(db: Session, current_doctor: Doctor):
    """Any day before today that reception never manually closed gets closed
    automatically, using system totals as the counted totals (i.e. assuming
    no variance was ever reported). Runs lazily whenever day-end data is
    read (a safety net alongside the midnight scheduler in app/scheduler.py,
    in case the process was down at midnight). Capped at 14 days back so a
    brand-new hospital with no history doesn't walk further than it needs to."""
    today = ist_today()
    for days_back in range(1, 15):
        d = today - timedelta(days=days_back)
        existing = db.query(DayEndClose).filter(
            DayEndClose.hospital_id == current_doctor.hospital_id, DayEndClose.close_date == d
        ).first()
        if existing:
            break  # everything older than this was already caught by a previous run
        closed = close_day_for_hospital(db, current_doctor.hospital_id, d, closed_by=current_doctor.id)
        if not closed:
            continue


@router.get("/day-end-summary")
def day_end_summary(
    date: str = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """§9 — system-logged collections for the day, broken out by mode and
    category, for reception to check their actual cash/card/UPI in hand
    against. Cash refunds issued that day are netted out of the cash total."""
    if current_doctor.role.value not in ["receptionist", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    if date is None:  # only auto-catch-up when viewing "today" — avoid recursion when auto-closing past days calls this same function
        auto_close_past_days(db, current_doctor)

    target_date = datetime.fromisoformat(date).date() if date else ist_today()
    return _day_end_summary_core(db, current_doctor.hospital_id, target_date)


def _day_end_summary_core(db: Session, hospital_id: int, target_date):
    """Plain, request-independent version of the day-end totals computation
    — used by the /day-end-summary endpoint above and by the midnight
    scheduler (app/scheduler.py), neither of which needs an authenticated
    current_doctor to run this."""
    day_start, day_end = ist_day_bounds(target_date)

    by_mode = {}

    def add(mode, category, amount):
        if not mode or not amount:
            return
        by_mode.setdefault(mode, {})
        by_mode[mode][category] = round(by_mode[mode].get(category, 0) + amount, 2)

    checkins = db.query(Checkin).filter(
        Checkin.hospital_id == hospital_id, Checkin.is_paid == True,
        Checkin.paid_at >= day_start, Checkin.paid_at < day_end
    ).all()
    for c in checkins:
        add(c.payment_method, "consultation", c.consultation_fee or 0)

    tests = db.query(TestOrder).filter(
        TestOrder.hospital_id == hospital_id, TestOrder.status != "payment_pending",
        TestOrder.paid_at >= day_start, TestOrder.paid_at < day_end
    ).all()
    for t in tests:
        add(t.payment_method, "tests", t.price or 0)

    charges = db.query(OpdCharge).filter(
        OpdCharge.hospital_id == hospital_id, OpdCharge.status == "paid",
        OpdCharge.paid_at >= day_start, OpdCharge.paid_at < day_end
    ).all()
    for ch in charges:
        add(ch.payment_method, "opd_charges", (ch.amount or 0) * (ch.quantity or 1))

    deposits = db.query(AdmissionDeposit).join(Admission, AdmissionDeposit.admission_id == Admission.id).filter(
        Admission.hospital_id == hospital_id,
        AdmissionDeposit.collected_at >= day_start, AdmissionDeposit.collected_at < day_end
    ).all()
    for d in deposits:
        category = "ipd_topups" if d.note == "Top-up collected" else "ipd_deposits"
        add(d.payment_method, category, d.amount or 0)

    settlements = db.query(Invoice).filter(
        Invoice.hospital_id == hospital_id, Invoice.generated_from == "admission_discharge",
        Invoice.generated_at >= day_start, Invoice.generated_at < day_end
    ).all()
    for inv in settlements:
        add(inv.payment_method, "ipd_settlements", inv.amount_collected or 0)

    cash_refunds = db.query(Refund).filter(
        Refund.hospital_id == hospital_id, Refund.channel == "cash",
        Refund.processed_at >= day_start, Refund.processed_at < day_end
    ).all()
    total_cash_refunds = round(sum(r.amount for r in cash_refunds), 2)

    system_totals = {mode: round(sum(cats.values()), 2) for mode, cats in by_mode.items()}
    system_totals["cash"] = round(system_totals.get("cash", 0) - total_cash_refunds, 2)

    existing_close = db.query(DayEndClose).filter(
        DayEndClose.hospital_id == hospital_id, DayEndClose.close_date == target_date
    ).first()

    return {
        "date": target_date.isoformat(),
        "by_mode": by_mode,
        "cash_refunds": total_cash_refunds,
        "system_totals": system_totals,
        "already_closed": bool(existing_close),
        "close": ({
            "counted_cash": existing_close.counted_cash, "counted_card": existing_close.counted_card, "counted_upi": existing_close.counted_upi,
            "notes": existing_close.notes, "closed_at": existing_close.closed_at.isoformat() if existing_close.closed_at else None,
        } if existing_close else None),
    }


@router.post("/day-end-close")
def close_day_end(
    body: DayEndCloseIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["receptionist", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    target_date = datetime.fromisoformat(body.date).date() if body.date else ist_today()
    existing = db.query(DayEndClose).filter(
        DayEndClose.hospital_id == current_doctor.hospital_id, DayEndClose.close_date == target_date
    ).first()
    if existing and current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=400, detail="This day is already closed — only an admin can re-close it")

    summary = day_end_summary(date=body.date, db=db, current_doctor=current_doctor)
    system_totals = summary["system_totals"]

    close = existing or DayEndClose(hospital_id=current_doctor.hospital_id, close_date=target_date, closed_by=current_doctor.id)
    if not existing:
        db.add(close)

    close.system_cash = system_totals.get("cash", 0)
    close.system_card = system_totals.get("card", 0)
    close.system_upi = system_totals.get("upi", 0)
    close.counted_cash = body.counted_cash
    close.counted_card = body.counted_card
    close.counted_upi = body.counted_upi
    close.notes = body.notes
    close.closed_by = current_doctor.id
    close.closed_at = now_ist_naive()
    db.commit()

    return {
        "message": "Day closed",
        "variance": {
            "cash": round(body.counted_cash - close.system_cash, 2),
            "card": round(body.counted_card - close.system_card, 2),
            "upi": round(body.counted_upi - close.system_upi, 2),
        }
    }


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

    hospital = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()
    items, subtotal, gst_total, grand_total = apply_gst(items, hospital)

    return {
        "items": items,
        "subtotal": subtotal,
        "gst_total": gst_total,
        "total": grand_total
    }