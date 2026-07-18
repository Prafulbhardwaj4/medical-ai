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
from app.utils.auth import get_current_doctor
from app.utils.audit import log_action
from app.services.pdf_service import generate_invoice_pdf
from app.utils.timezone import ist_today, ist_day_bounds, ist_date

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
        billed = m.billed_quantity if m.billed_quantity is not None else m.quantity
        items.append({
            "type": "medicine",
            "name": f"{m.medicine_name}{' (' + m.brand_name + ')' if m.brand_name else ''}",
            "qty": billed or 1,
            "unit_price": m.unit_price or 0,
            "line_total": (m.unit_price or 0) * (billed or 1)
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
    consulting_doctor = db.query(Doctor).filter(Doctor.id == checkin.doctor_id).first()

    pdf_path = generate_invoice_pdf(invoice.id, hospital, items, grand_total, patient, consulting_doctor)
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
        target_label=f"Rs.{grand_total} for checkin {checkin_id}",
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
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    patient = db.query(Patient).filter(Patient.id == invoice.patient_id).first()
    hospital = db.query(Hospital).filter(Hospital.id == invoice.hospital_id).first()
    items = json.loads(invoice.items_json)

    checkin_for_doctor = db.query(Checkin).filter(Checkin.id == invoice.checkin_id).first()
    consulting_doctor = db.query(Doctor).filter(Doctor.id == checkin_for_doctor.doctor_id).first() if checkin_for_doctor else None
    pdf_path = generate_invoice_pdf(invoice.id, hospital, items, invoice.grand_total, patient, consulting_doctor)
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


# Revenue History (admin) — aggregate totals, not individual invoices (that's /invoices above).
# Deliberately bounded (3 months daily / 18 months monthly) rather than "since hospital
# creation": covers every real use an admin has (this week, month-over-month, year-over-year
# comparison) while keeping the query fast regardless of how long a hospital has been running.
# Computed live from Invoice rows each call, no rollup table — fine at real single-hospital
# invoice volumes, and each hospital's query only ever touches its own bounded window, so this
# doesn't get slower as more hospitals use the platform. Revisit only if one specific hospital's
# window genuinely gets big enough to matter, not preemptively.
MAX_DAILY_RANGE_DAYS = 92          # ~3 months
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
        buckets[d]["total"] += inv.grand_total
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
        buckets[key]["total"] += inv.grand_total
        buckets[key]["invoice_count"] += 1

    return {
        "from_month": f"{from_d.year:04d}-{from_d.month:02d}",
        "to_month": f"{to_d.year:04d}-{to_d.month:02d}",
        "months": [
            {"month": f"{y:04d}-{m:02d}", "total": round(v["total"], 2), "invoice_count": v["invoice_count"]}
            for (y, m), v in sorted(buckets.items())
        ]
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

    return {
        "items": items,
        "total": sum(i["line_total"] for i in items)
    }