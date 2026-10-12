from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.refund import Refund
from app.models.invoice import Invoice
from app.models.hospital import Hospital
from app.models.credit_debit_note import CreditDebitNote
from app.models.checkin import Checkin
from app.models.opd_charge import OpdCharge
from app.schemas.billing import RefundIn
from app.utils.auth import get_current_doctor
from app.utils.receipts import next_note_number
from app.utils.audit import log_action
from app.utils.timezone import now_ist_naive

router = APIRouter(prefix="/refunds", tags=["refunds"])

VALID_SOURCE_TYPES = {"appointment", "pharmacy", "ipd_deposit", "opd_charge", "test", "other"}
VALID_CHANNELS = {"cash", "card", "upi", "online"}
# Money only physically leaves by one of these; "online" stays only because older records and pharmacy still use the label.
SETTLE_CHANNELS = {"cash", "card", "upi"}
SOURCE_LABELS = {
    "appointment": "Appointment fee",
    "test": "Test fee",
    "pharmacy": "Pharmacy",
    "ipd_deposit": "IPD deposit balance",
    "opd_charge": "OPD charge",
    "other": "Other",
}

from datetime import timedelta
from typing import Optional
from pydantic import BaseModel
from sqlalchemy import func
from app.routers.attendance import require_present
from app.utils.refund_notify import notify_admin_refund


def _require_refund_staff(current_doctor: Doctor):
    if current_doctor.role.value != "receptionist":
        raise HTTPException(status_code=403, detail="Only reception can pay out refunds")


@router.post("")
def create_refund(body: RefundIn, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    _require_refund_staff(current_doctor)
    if body.source_type not in VALID_SOURCE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid source_type")
    if body.channel not in SETTLE_CHANNELS:
        raise HTTPException(status_code=400, detail="Refund channel must be cash, card or UPI")
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero")

    patient = db.query(Patient).filter(Patient.id == body.patient_id, Patient.hospital_id == current_doctor.hospital_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    invoice = None
    if body.invoice_id:
        raise HTTPException(status_code=400, detail="Money that is already billed on an invoice cannot be refunded")

    if body.checkin_id and body.invoice_id:
        raise HTTPException(status_code=400, detail="Provide only one of checkin_id or invoice_id")

    checkin = None
    if body.checkin_id:
        checkin = db.query(Checkin).filter(
            Checkin.id == body.checkin_id,
            Checkin.hospital_id == current_doctor.hospital_id,
            Checkin.patient_id == body.patient_id
        ).first()
        if not checkin:
            raise HTTPException(status_code=404, detail="Visit not found for this patient")
        if checkin.is_finalized:
            raise HTTPException(status_code=400, detail="This visit's invoice is already finalized — link this refund to the invoice instead so it issues a credit note")

    refund = Refund(
        patient_id=body.patient_id, hospital_id=current_doctor.hospital_id,
        source_type=body.source_type, source_id=body.source_id, amount=body.amount,
        channel=body.channel, status="completed",
        reason=body.reason, processed_by=current_doctor.id,
        settled_at=now_ist_naive(), settled_by=current_doctor.id,
    )
    db.add(refund)
    db.flush()
    notify_admin_refund(db, refund, current_doctor, patient.name)
    db.commit()
    db.refresh(refund)

    # Item 4 fix: a refund against a visit that hasn't been billed yet has
    # nothing to correct — instead of just logging cash out the door, add a
    # negative OPD charge (same mechanism waivers already use) so the item
    # nets out automatically the next time this checkin's invoice is
    # finalized, rather than the refunded item still showing up as a full,
    # uncredited charge.
    if checkin:
        db.add(OpdCharge(
            checkin_id=checkin.id, patient_id=checkin.patient_id, hospital_id=checkin.hospital_id,
            description=f"Refund adjustment — {body.reason or 'refund issued'}", amount=-abs(body.amount), quantity=1,
            added_by=current_doctor.id, status="paid", paid_at=now_ist_naive(),
        ))
        db.commit()

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


class SettleRefundIn(BaseModel):
    channel: str


class DismissRefundIn(BaseModel):
    reason: str


def _already_billed(db: Session, r: Refund) -> bool:
    """A consultation fee that's already on an issued invoice is billed money — it can't be refunded."""
    if r.source_type == "appointment" and r.source_id:
        chk = db.query(Checkin).filter(Checkin.portal_appointment_id == r.source_id).first()
        return bool(chk and chk.invoice_id)
    return False


def _suggested_channel(db: Session, r: Refund) -> str:
    from app.models.portal import Appointment
    from app.models.test_order import TestOrder
    from app.models.medicine_order import MedicineOrder
    model = {"appointment": Appointment, "test": TestOrder, "pharmacy": MedicineOrder, "opd_charge": OpdCharge}.get(r.source_type)
    if model is not None and r.source_id:
        row = db.query(model.payment_method).filter(model.id == r.source_id).first()
        if row and row[0] in SETTLE_CHANNELS:
            return row[0]
    return r.channel if r.channel in SETTLE_CHANNELS else "cash"


def _serialize_refund(db: Session, r: Refund, patients: dict, staff: dict) -> dict:
    p = patients.get(r.patient_id)
    name = p.name if p else None
    if not name and r.source_type == "appointment" and r.source_id:
        from app.models.portal import Appointment
        row = db.query(Appointment.new_patient_name).filter(Appointment.id == r.source_id).first()
        name = row[0] if row and row[0] else None
    admission_token = None
    if r.source_type == "ipd_deposit" and r.source_id:
        from app.models.admission import Admission
        row = db.query(Admission.public_token).filter(Admission.id == r.source_id).first()
        admission_token = row[0] if row else None
    by_id = r.settled_by or r.processed_by
    return {
        "id": r.id,
        "patient_name": name or "Portal patient",
        "patient_uid": p.patient_uid if p else None,
        "source_type": r.source_type,
        "source_label": SOURCE_LABELS.get(r.source_type, r.source_type),
        "amount": r.amount,
        "reason": r.reason,
        "channel": r.channel,
        "suggested_channel": _suggested_channel(db, r) if r.status == "pending" else None,
        "status": r.status,
        "already_billed": _already_billed(db, r) if r.status == "pending" else False,
        "raised_at": r.processed_at.isoformat() if r.processed_at else None,
        "paid_at": (r.settled_at or r.processed_at).isoformat() if r.status != "pending" and (r.settled_at or r.processed_at) else None,
        "paid_by_name": staff.get(by_id) if r.status != "pending" else None,
        "admission_token": admission_token,
    }


@router.get("")
def list_refunds(db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    """Reception's Refunds page: everything still owed (any age) plus the last 30 days of paid/closed refunds."""
    _require_refund_staff(current_doctor)
    hospital_id = current_doctor.hospital_id
    cutoff = now_ist_naive() - timedelta(days=30)
    paid_on = func.coalesce(Refund.settled_at, Refund.processed_at)

    pending = db.query(Refund).filter(
        Refund.hospital_id == hospital_id, Refund.status == "pending"
    ).order_by(Refund.processed_at.asc()).all()
    history = db.query(Refund).filter(
        Refund.hospital_id == hospital_id, Refund.status.in_(["completed", "dismissed"]), paid_on >= cutoff
    ).order_by(paid_on.desc()).all()

    rows = pending + history
    patient_ids = {r.patient_id for r in rows if r.patient_id}
    patients = {p.id: p for p in db.query(Patient).filter(Patient.id.in_(patient_ids)).all()} if patient_ids else {}
    staff_ids = {i for r in rows for i in (r.settled_by, r.processed_by) if i}
    staff = {d.id: d.name for d in db.query(Doctor).filter(Doctor.id.in_(staff_ids)).all()} if staff_ids else {}

    return {
        "pending": [_serialize_refund(db, r, patients, staff) for r in pending],
        "history": [_serialize_refund(db, r, patients, staff) for r in history],
        "history_paid_total": round(sum((r.amount or 0) for r in history if r.status == "completed"), 2),
    }


@router.post("/{refund_id}/settle")
def settle_refund(refund_id: int, body: SettleRefundIn, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    """Reception has handed the money back. Only now does it leave Collected
    (netted against the day the original money came in) and the day-end till."""
    _require_refund_staff(current_doctor)
    require_present(db, current_doctor)
    if body.channel not in SETTLE_CHANNELS:
        raise HTTPException(status_code=400, detail="Refund channel must be cash, card or UPI")
    r = db.query(Refund).filter(Refund.id == refund_id, Refund.hospital_id == current_doctor.hospital_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Refund not found")
    if r.status != "pending":
        raise HTTPException(status_code=400, detail="This refund is already closed")
    if _already_billed(db, r):
        raise HTTPException(status_code=400, detail="This fee is already on an issued invoice. Billed money cannot be refunded — close this refund instead.")

    r.channel = body.channel
    r.status = "completed"
    r.settled_at = now_ist_naive()
    r.settled_by = current_doctor.id
    db.flush()
    patient = db.query(Patient).filter(Patient.id == r.patient_id).first() if r.patient_id else None
    notify_admin_refund(db, r, current_doctor, patient.name if patient else None, kind="paid")
    db.commit()
    log_action(
        db, current_doctor,
        action="refund_paid",
        target_type="refund",
        target_id=r.id,
        details=f"{r.source_type} #{r.source_id}, Rs.{r.amount:.2f} by {r.channel}",
    )
    return {"message": "Refund recorded as paid"}


@router.post("/{refund_id}/dismiss")
def dismiss_refund(refund_id: int, body: DismissRefundIn, db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    """Reception closes a pending refund without paying it (e.g. fee already billed,
    patient waived it). Never touches Collected. Reason is required and goes to admin."""
    _require_refund_staff(current_doctor)
    why = (body.reason or "").strip()
    if len(why) < 3:
        raise HTTPException(status_code=400, detail="Please give a reason")
    r = db.query(Refund).filter(Refund.id == refund_id, Refund.hospital_id == current_doctor.hospital_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Refund not found")
    if r.status != "pending":
        raise HTTPException(status_code=400, detail="This refund is already closed")

    r.status = "dismissed"
    r.reason = f"{r.reason or 'Refund'} — not paid: {why}"
    r.settled_at = now_ist_naive()
    r.settled_by = current_doctor.id
    db.flush()
    patient = db.query(Patient).filter(Patient.id == r.patient_id).first() if r.patient_id else None
    notify_admin_refund(db, r, current_doctor, patient.name if patient else None, kind="dismissed")
    db.commit()
    log_action(
        db, current_doctor,
        action="refund_dismissed",
        target_type="refund",
        target_id=r.id,
        details=f"{r.source_type} #{r.source_id}, Rs.{r.amount:.2f}. Reason: {why}",
    )
    return {"message": "Refund closed without payment"}