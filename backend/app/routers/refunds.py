from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.refund import Refund
from app.models.invoice import Invoice
from app.models.hospital import Hospital
from app.models.credit_debit_note import CreditDebitNote
from app.schemas.billing import RefundIn
from app.utils.auth import get_current_doctor
from app.utils.receipts import next_note_number

router = APIRouter(prefix="/refunds", tags=["refunds"])

VALID_SOURCE_TYPES = {"appointment", "pharmacy", "ipd_deposit", "opd_charge", "tpa", "other"}
VALID_CHANNELS = {"cash", "card", "upi", "online"}


def _require_refund_staff(current_doctor: Doctor):
    if current_doctor.role.value not in ["receptionist", "pharmacy", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized to record refunds")


@router.post("")
def create_refund(body: RefundIn, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    _require_refund_staff(current_doctor)
    if body.source_type not in VALID_SOURCE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid source_type")
    if body.channel not in VALID_CHANNELS:
        raise HTTPException(status_code=400, detail="Invalid channel")
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero")

    patient = db.query(Patient).filter(Patient.id == body.patient_id, Patient.hospital_id == current_doctor.hospital_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    invoice = None
    if body.invoice_id:
        invoice = db.query(Invoice).filter(
            Invoice.id == body.invoice_id,
            Invoice.hospital_id == current_doctor.hospital_id,
            Invoice.patient_id == body.patient_id
        ).first()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found for this patient")

    refund = Refund(
        patient_id=body.patient_id, hospital_id=current_doctor.hospital_id,
        source_type=body.source_type, source_id=body.source_id, amount=body.amount,
        channel=body.channel, status="pending" if body.channel == "online" else "completed",
        reason=body.reason, processed_by=current_doctor.id,
    )
    db.add(refund)
    db.commit()
    db.refresh(refund)

    # A refund against a real invoice is a GST-relevant correction — it
    # can't just be a cash-transaction log entry, it needs its own
    # supplementary document referencing the original invoice.
    credit_note_number = None
    if invoice:
        hospital = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()
        note = CreditDebitNote(
            hospital_id=current_doctor.hospital_id,
            invoice_id=invoice.id,
            patient_id=invoice.patient_id,
            note_type="credit",
            note_number=next_note_number(db, hospital, "credit"),
            invoice_number=invoice.receipt_number,
            invoice_date=invoice.generated_at,
            amount=body.amount,
            reason=body.reason or "Refund issued",
            refund_id=refund.id,
            created_by=current_doctor.id,
        )
        db.add(note)
        db.commit()
        credit_note_number = note.note_number

    return {"message": "Refund recorded", "id": refund.id, "status": refund.status, "credit_note_number": credit_note_number}


@router.get("/patient/{patient_id}")
def list_patient_refunds(patient_id: int, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    refunds = db.query(Refund).filter(
        Refund.patient_id == patient_id, Refund.hospital_id == current_doctor.hospital_id
    ).order_by(Refund.processed_at.desc()).all()
    return [
        {"id": r.id, "source_type": r.source_type, "source_id": r.source_id, "amount": r.amount,
         "channel": r.channel, "status": r.status, "reason": r.reason,
         "processed_at": r.processed_at.isoformat() if r.processed_at else None}
        for r in refunds
    ]


@router.patch("/{refund_id}/mark-settled")
def mark_refund_settled(refund_id: int, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    refund = db.query(Refund).filter(Refund.id == refund_id, Refund.hospital_id == current_doctor.hospital_id).first()
    if not refund:
        raise HTTPException(status_code=404, detail="Refund not found")
    if refund.status != "pending":
        raise HTTPException(status_code=400, detail="Only a pending refund can be marked settled")
    refund.status = "completed"
    db.commit()
    return {"message": "Refund marked settled"}