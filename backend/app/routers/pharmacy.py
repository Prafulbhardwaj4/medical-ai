from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_
from datetime import date, datetime
import json

from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from app.database import get_db
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.consultation import Consultation
from app.models.medicine_order import MedicineOrder
from app.models.medicine_order_return import MedicineOrderReturn
from app.models.hospital_medicine import HospitalMedicine
from app.models.refund import Refund
from app.utils.auth import get_current_doctor, ist_today, ist_day_bounds
from app.utils.timezone import now_ist_naive
from app.utils.audit import log_action
from app.utils.order_lifecycle import is_order_expired
from app.routers.attendance import require_present
from app.routers.refunds import VALID_CHANNELS

router = APIRouter(prefix="/pharmacy", tags=["pharmacy"])


def require_pharmacy(current_doctor: Doctor):
    if current_doctor.role.value not in ["pharmacy", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")


def _generic_identity(db: Session, catalog_medicine_id: int):
    """Resolves a catalog row — which may be a brand-specific row — to the
    underlying generic drug identity, so Schedule X repeat checks match
    across different brands of the same controlled substance."""
    med = db.query(HospitalMedicine).filter(HospitalMedicine.id == catalog_medicine_id).first()
    if not med:
        return None
    if med.parent_medicine_id:
        parent = db.query(HospitalMedicine).filter(HospitalMedicine.id == med.parent_medicine_id).first()
        if parent:
            return parent.generic_name
    return med.generic_name


def _schedule_x_repeat_block(db: Session, order: "MedicineOrder"):
    """Returns a blocking error message if this Schedule X order is an
    unauthorized repeat dispense for this patient, else None."""
    if not order.catalog_medicine_id:
        return None
    medicine = db.query(HospitalMedicine).filter(HospitalMedicine.id == order.catalog_medicine_id).first()
    if not medicine or medicine.schedule != "x":
        return None

    generic = _generic_identity(db, order.catalog_medicine_id)
    if not generic:
        return None

    prior = db.query(MedicineOrder).join(
        HospitalMedicine, MedicineOrder.catalog_medicine_id == HospitalMedicine.id
    ).filter(
        MedicineOrder.patient_id == order.patient_id,
        MedicineOrder.hospital_id == order.hospital_id,
        MedicineOrder.status == "dispensed",
        MedicineOrder.id != order.id,
        HospitalMedicine.schedule == "x",
    ).all()
    has_prior = any(_generic_identity(db, p.catalog_medicine_id) == generic for p in prior)

    if has_prior and not order.repeat_authorized:
        return f"{order.medicine_name} is a Schedule X repeat dispense for this patient — needs doctor authorization before it can be dispensed again."
    return None


@router.get("/admission-queue")
def get_pharmacy_admission_queue(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Medicines doctors have ordered for currently-admitted patients — visibility
    only, no payment collected here (billed automatically at order time, in
    admissions.py). Pharmacy just needs to see what to send to the ward and
    mark it sent. A still-pending order shows regardless of age; once
    dispensed, it stays visible for the rest of the day it was sent (so the
    "sent" confirmation doesn't vanish mid-shift) and drops off the next day."""
    require_pharmacy(current_doctor)
    from app.models.admission import Admission, AdmissionMedicationOrder

    today_start, today_end = ist_day_bounds()

    orders = (
        db.query(AdmissionMedicationOrder, Admission)
        .join(Admission, AdmissionMedicationOrder.admission_id == Admission.id)
        .filter(
            Admission.hospital_id == current_doctor.hospital_id,
            Admission.status == "admitted",
            AdmissionMedicationOrder.is_active == True,  # noqa: E712
            AdmissionMedicationOrder.sourced_outside == False,  # noqa: E712
            or_(
                AdmissionMedicationOrder.dispensed_at == None,  # noqa: E711
                AdmissionMedicationOrder.dispensed_at.between(today_start, today_end),
            ),
        )
        .order_by(AdmissionMedicationOrder.created_at.desc())
        .all()
    )

    result = []
    for o, a in orders:
        patient = db.query(Patient).filter(Patient.id == a.patient_id).first()
        medicine = db.query(HospitalMedicine).filter(HospitalMedicine.id == o.medicine_id).first() if o.medicine_id else None
        prescriber = db.query(Doctor).filter(Doctor.id == o.prescribed_by).first() if o.prescribed_by else None
        result.append({
            "id": o.id,
            "admission_id": a.id,
            "admission_token": a.public_token,
            "patient_id": a.patient_id,
            "patient_name": patient.name if patient else "Unknown",
            "ward": a.ward,
            "bed_number": a.bed_number,
            "medicine_name": o.medicine_name,
            "strength": medicine.strength if medicine else None,
            "quantity": o.quantity,
            "dosage": o.dosage,
            "route": o.route,
            "frequency_note": o.frequency_note,
            "prescriber_name": f"{prescriber.title} {prescriber.name}" if prescriber else None,
            "prescriber_role": prescriber.role.value if prescriber else None,
            "ordered_at": o.created_at.isoformat() if o.created_at else None,
            "dispensed_at": o.dispensed_at.isoformat() if o.dispensed_at else None,
            "is_out_of_stock": o.is_out_of_stock,
        })
    return result


@router.post("/admission-orders/{order_id}/dispense")
def dispense_admission_medicine(
    order_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Marks a medicine order as physically handed to the ward. Billing and
    stock deduction now happen upfront at ORDER time (see add_medication_order
    in admissions.py) — this endpoint used to also bill and deduct stock here,
    which meant every dispensed admission medicine was charged twice and
    double-deducted from stock once the order-time billing was added. This
    just records who/when it was physically sent, nothing financial."""
    require_pharmacy(current_doctor)
    from app.models.admission import Admission, AdmissionMedicationOrder

    order = (
        db.query(AdmissionMedicationOrder)
        .join(Admission, AdmissionMedicationOrder.admission_id == Admission.id)
        .filter(AdmissionMedicationOrder.id == order_id, Admission.hospital_id == current_doctor.hospital_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.dispensed_at:
        raise HTTPException(status_code=400, detail="Already dispensed")

    order.dispensed_at = now_ist_naive()
    order.dispensed_by = current_doctor.id
    db.commit()
    return {"message": "Marked as sent to ward"}

class SubstituteAdmissionMedIn(BaseModel):
    medicine_id: Optional[int] = None
    medicine_name: str
    manual_unit_price: Optional[float] = None


@router.post("/admission-orders/{order_id}/mark-out-of-stock")
def mark_admission_medicine_out_of_stock(
    order_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Flags an already-ordered/billed admission medicine as unavailable at
    the pharmacy counter. This never touches billing or stock — those
    already happened upfront at order time — it just hides the normal
    Sent/Dispensed action on this order and opens up the Substitute flow."""
    require_pharmacy(current_doctor)
    from app.models.admission import Admission, AdmissionMedicationOrder

    order = (
        db.query(AdmissionMedicationOrder)
        .join(Admission, AdmissionMedicationOrder.admission_id == Admission.id)
        .filter(AdmissionMedicationOrder.id == order_id, Admission.hospital_id == current_doctor.hospital_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.dispensed_at:
        raise HTTPException(status_code=400, detail="Already dispensed")

    order.is_out_of_stock = True
    db.commit()
    return {"message": "Marked out of stock"}


@router.post("/admission-orders/{order_id}/substitute")
def substitute_admission_medicine(
    order_id: int,
    body: SubstituteAdmissionMedIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Replaces an out-of-stock admission medicine order with a substitute.
    The original was already billed and stock-deducted upfront at order
    time, before the shortage was found, so this reverses that charge with
    a negative line (same pattern as a medication return) and bills/stock-
    deducts the substitute in its place. The admitting doctor is notified
    by name, naming both the substitute medicine and the staff member who
    made the call, since they never approved this specific swap."""
    require_pharmacy(current_doctor)
    from app.models.admission import Admission, AdmissionMedicationOrder, AdmissionCharge
    from app.models.notification import Notification
    from app.utils.inventory import deduct_stock_fefo

    original = (
        db.query(AdmissionMedicationOrder)
        .join(Admission, AdmissionMedicationOrder.admission_id == Admission.id)
        .filter(AdmissionMedicationOrder.id == order_id, Admission.hospital_id == current_doctor.hospital_id)
        .first()
    )
    if not original:
        raise HTTPException(status_code=404, detail="Order not found")
    if not original.is_out_of_stock:
        raise HTTPException(status_code=400, detail="Only an order marked out of stock can be substituted")
    if original.dispensed_at:
        raise HTTPException(status_code=400, detail="Already dispensed")

    a = db.query(Admission).filter(Admission.id == original.admission_id).first()

    medicine = None
    unit_price = 0.0
    if body.medicine_id:
        medicine = db.query(HospitalMedicine).filter(
            HospitalMedicine.id == body.medicine_id, HospitalMedicine.hospital_id == current_doctor.hospital_id
        ).first()
        if not medicine:
            raise HTTPException(status_code=404, detail="Medicine not found in catalog")
        unit_price = medicine.price_per_pack if medicine.price_per_pack else (medicine.price or 0) * (medicine.pack_size or 1)
    else:
        unit_price = body.manual_unit_price or 0.0

    if not original.sourced_outside:
        original_medicine = db.query(HospitalMedicine).filter(HospitalMedicine.id == original.medicine_id).first() if original.medicine_id else None
        original_unit_price = original.manual_unit_price if original.manual_unit_price is not None else (
            (original_medicine.price_per_pack if original_medicine and original_medicine.price_per_pack else ((original_medicine.price or 0) * (original_medicine.pack_size or 1)) if original_medicine else 0) or 0
        )
        db.add(AdmissionCharge(
            admission_id=a.id, charge_type="medicine",
            description=f"{original.medicine_name} — reversed, out of stock",
            amount=-original_unit_price, quantity=original.quantity, added_by=current_doctor.id, charged_at=now_ist_naive(),
        ))

    new_order = AdmissionMedicationOrder(
        admission_id=a.id, medicine_id=body.medicine_id, medicine_name=body.medicine_name,
        quantity=original.quantity,
        manual_unit_price=(body.manual_unit_price if not body.medicine_id else None),
        prescribed_by=original.prescribed_by,
        substitute_for_id=original.id,
    )
    db.add(new_order)

    if not original.sourced_outside:
        if body.medicine_id:
            deduct_stock_fefo(db, body.medicine_id, original.quantity * (medicine.pack_size or 1), round_to_pack=True)
        db.add(AdmissionCharge(
            admission_id=a.id, charge_type="medicine", description=body.medicine_name,
            amount=unit_price, quantity=original.quantity, added_by=current_doctor.id, charged_at=now_ist_naive(),
        ))

    original.is_active = False
    db.flush()

    patient = db.query(Patient).filter(Patient.id == a.patient_id).first()
    db.add(Notification(
        hospital_id=a.hospital_id, target_doctor_id=original.prescribed_by,
        source_key=f"admission_med_substitute:{new_order.id}:{now_ist_naive().isoformat()}",
        type="admission_medicine_substitute", severity="info",
        title=f"Medicine substituted — {patient.name if patient else 'patient'}",
        message=f"{original.medicine_name} was out of stock and substituted with {body.medicine_name} by {current_doctor.title} {current_doctor.name}.",
        link_type="admission_medicine_order", link_id=a.id, is_read=False,
    ))

    db.commit()
    db.refresh(new_order)
    return {"id": new_order.id, "message": "Substituted"}


@router.get("/admission-orders-history/{admission_id}")
def get_admission_medicine_dispense_history(
    admission_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Every medicine actually handed over to this admission's ward, most
    recent first — this data is never purged, so it stays available for the
    rest of the stay and beyond (including after discharge)."""
    require_pharmacy(current_doctor)
    from app.models.admission import Admission, AdmissionMedicationOrder

    a = db.query(Admission).filter(Admission.id == admission_id, Admission.hospital_id == current_doctor.hospital_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Admission not found")

    orders = (
        db.query(AdmissionMedicationOrder)
        .filter(AdmissionMedicationOrder.admission_id == a.id, AdmissionMedicationOrder.dispensed_at.isnot(None))
        .order_by(AdmissionMedicationOrder.dispensed_at.desc())
        .all()
    )
    result = []
    for o in orders:
        dispenser = db.query(Doctor).filter(Doctor.id == o.dispensed_by).first() if o.dispensed_by else None
        result.append({
            "id": o.id,
            "medicine_name": o.medicine_name,
            "quantity": o.quantity,
            "dispensed_at": o.dispensed_at.isoformat() if o.dispensed_at else None,
            "dispensed_by": f"{dispenser.title} {dispenser.name}" if dispenser else None,
        })
    return result

@router.get("/queue")
def get_pharmacy_queue(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_pharmacy(current_doctor)

    today_start, today_end = ist_day_bounds()

    requeued_consultation_ids = [
        row[0] for row in db.query(MedicineOrder.consultation_id).filter(
            MedicineOrder.hospital_id == current_doctor.hospital_id,
            MedicineOrder.queued_at >= today_start,
            MedicineOrder.queued_at <= today_end
        ).distinct().all()
    ]

    rows = (
        db.query(Consultation, Patient)
        .join(Patient, Consultation.patient_id == Patient.id)
        .filter(
            Patient.hospital_id == current_doctor.hospital_id,
            Consultation.token_number != None,
            Consultation.is_voided == False,
            or_(
                Consultation.created_at.between(today_start, today_end),
                Consultation.id.in_(requeued_consultation_ids) if requeued_consultation_ids else False
            )
        )
        .order_by(desc(Consultation.created_at))
        .all()
    )

    return [
        {
            "token_number": c.token_number,
            "patient_name": p.name,
            "confirmed_at": c.created_at.isoformat(),
            "is_dispensed": c.is_dispensed,
            "dispensed_at": c.dispensed_at.isoformat() if c.dispensed_at else None,
            "verify_hash": c.verify_hash
        }
        for c, p in rows
    ]


@router.get("/prescription/{token_number}")
def get_pharmacy_prescription(
    token_number: str,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_pharmacy(current_doctor)

    consultation = db.query(Consultation).filter(
        Consultation.token_number == token_number,
        Consultation.is_voided == False
    ).first()
    if not consultation:
        raise HTTPException(status_code=404, detail="Prescription not found")

    patient = db.query(Patient).filter(
        Patient.id == consultation.patient_id,
        Patient.hospital_id == current_doctor.hospital_id
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Prescription not found")

    doctor = db.query(Doctor).filter(Doctor.id == consultation.doctor_id).first()
    medicines = json.loads(consultation.medicines or "[]")

    medicine_orders = db.query(MedicineOrder).filter(
        MedicineOrder.consultation_id == consultation.id
    ).order_by(MedicineOrder.id).all()

    return {
        "token_number": consultation.token_number,
        "patient_name": patient.name,
        "patient_age": patient.age,
        "patient_gender": patient.gender,
        "doctor_name": f"{doctor.title} {doctor.name}" if doctor else "—",
        "confirmed_at": consultation.created_at.isoformat(),
        "medicines": medicines,
        "medicine_orders": [serialize_medicine_order(m, db) for m in medicine_orders],
        "is_dispensed": consultation.is_dispensed,
        "dispensed_at": consultation.dispensed_at.isoformat() if consultation.dispensed_at else None,
        "verify_hash": consultation.verify_hash
    }


def serialize_medicine_order(m: MedicineOrder, db: Session = None):
    stock_quantity = None
    low_stock_threshold = None
    schedule = None
    if db is not None and m.catalog_medicine_id:
        catalog_item = db.query(HospitalMedicine).filter(HospitalMedicine.id == m.catalog_medicine_id).first()
        if catalog_item:
            stock_quantity = catalog_item.stock_quantity
            low_stock_threshold = catalog_item.low_stock_threshold
            schedule = catalog_item.schedule

    already_returned = 0
    if db is not None and m.status == "dispensed":
        from app.models.medicine_order_return import MedicineOrderReturn
        already_returned = sum(r.quantity for r in db.query(MedicineOrderReturn).filter(MedicineOrderReturn.order_id == m.id).all())

    billed = m.billed_quantity if m.billed_quantity is not None else m.quantity
    return {
        "id": m.id,
        "medicine_name": m.medicine_name,
        "brand_name": m.brand_name or "",
        "dosage": m.dosage or "",
        "frequency": m.frequency or "",
        "duration": m.duration or "",
        "catalog_medicine_id": m.catalog_medicine_id,
        "schedule": schedule,
        "unit_price": m.unit_price,
        "quantity": m.quantity,
        "billed_quantity": m.billed_quantity,
        "line_total": (m.unit_price * billed) if (m.unit_price is not None and billed is not None) else None,
        "included": m.included,
        "status": m.status,
        "substitute_for_id": m.substitute_for_id,
        "stock_quantity": stock_quantity,
        "low_stock_threshold": low_stock_threshold,
        "repeat_authorized": m.repeat_authorized,
        "already_returned": already_returned,
    }


class QuantityIn(BaseModel):
    quantity: int


class LinkCatalogIn(BaseModel):
    catalog_medicine_id: int


@router.patch("/medicine-orders/{order_id}/toggle-include")
def toggle_medicine_order_include(
    order_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_pharmacy(current_doctor)
    require_present(db, current_doctor)

    order = db.query(MedicineOrder).filter(
        MedicineOrder.id == order_id,
        MedicineOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Medicine order not found")
    if order.status not in ("advised", "unavailable"):
        raise HTTPException(status_code=400, detail="Cannot change inclusion after payment")

    order.included = not order.included
    # Unchecking now behaves exactly like "advised outside" — excluded from
    # payment AND from stock deduction at dispense. Re-checking reverts it
    # to a normal advised line so it can be paid/dispensed again.
    order.status = "unavailable" if not order.included else "advised"
    db.commit()
    return {"id": order.id, "included": order.included, "status": order.status}


@router.patch("/medicine-orders/{order_id}/quantity")
def set_medicine_order_quantity(
    order_id: int,
    payload: QuantityIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_pharmacy(current_doctor)
    require_present(db, current_doctor)

    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than 0")

    order = db.query(MedicineOrder).filter(
        MedicineOrder.id == order_id,
        MedicineOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Medicine order not found")
    if order.status != "advised":
        raise HTTPException(status_code=400, detail="Cannot change quantity after payment")

    order.quantity = payload.quantity
    db.commit()
    return serialize_medicine_order(order, db)


@router.patch("/medicine-orders/{order_id}/link-catalog")
def link_medicine_order_catalog(
    order_id: int,
    payload: LinkCatalogIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_pharmacy(current_doctor)
    require_present(db, current_doctor)

    order = db.query(MedicineOrder).filter(
        MedicineOrder.id == order_id,
        MedicineOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Medicine order not found")
    if order.status != "advised":
        raise HTTPException(status_code=400, detail="Cannot relink after payment")

    catalog_item = db.query(HospitalMedicine).filter(
        HospitalMedicine.id == payload.catalog_medicine_id,
        HospitalMedicine.hospital_id == current_doctor.hospital_id,
        HospitalMedicine.is_active == True
    ).first()
    if not catalog_item:
        raise HTTPException(status_code=404, detail="Catalog medicine not found")

    order.catalog_medicine_id = catalog_item.id
    order.unit_price = catalog_item.price
    db.commit()
    return serialize_medicine_order(order, db)


@router.get("/medicines/search")
def search_medicines_for_linking(
    q: str = "",
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_pharmacy(current_doctor)

    query = db.query(HospitalMedicine).filter(
        HospitalMedicine.hospital_id == current_doctor.hospital_id,
        HospitalMedicine.is_active == True
    )
    if q:
        like = f"%{q}%"
        query = query.filter(
            HospitalMedicine.generic_name.ilike(like)
            | HospitalMedicine.brand_names.ilike(like)
            | HospitalMedicine.brand_name.ilike(like)
        )

    items = query.order_by(HospitalMedicine.generic_name).limit(20).all()
    return [
        {"id": m.id, "generic_name": m.generic_name, "brand_names": m.brand_name or m.brand_names or "", "price": m.price, "strength": m.strength or ""}
        for m in items
    ]


@router.post("/prescription/{token_number}/collect-payment")
def collect_medicine_payment(
    token_number: str,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_pharmacy(current_doctor)
    require_present(db, current_doctor)

    consultation = db.query(Consultation).filter(
        Consultation.token_number == token_number,
        Consultation.is_voided == False
    ).first()
    if not consultation:
        raise HTTPException(status_code=404, detail="Prescription not found")

    orders = db.query(MedicineOrder).filter(
        MedicineOrder.consultation_id == consultation.id,
        MedicineOrder.hospital_id == current_doctor.hospital_id,
        MedicineOrder.included == True,
        MedicineOrder.status == "advised"
    ).all()

    if not orders:
        raise HTTPException(status_code=400, detail="No included medicines pending payment")

    missing_price = [o.medicine_name for o in orders if o.unit_price is None or o.quantity is None]
    if missing_price:
        raise HTTPException(
            status_code=400,
            detail=f"Set price and quantity first for: {', '.join(missing_price)}"
        )

    blocking = []
    for o in orders:
        if o.catalog_medicine_id:
            catalog_item = db.query(HospitalMedicine).filter(HospitalMedicine.id == o.catalog_medicine_id).first()
            if catalog_item and catalog_item.stock_quantity is not None and catalog_item.stock_quantity <= 0:
                blocking.append(o.medicine_name)
    if blocking:
        raise HTTPException(
            status_code=400,
            detail=f"Out of stock — substitute or mark advised-outside before collecting payment: {', '.join(blocking)}"
        )

    total = 0
    charged_count = 0
    skipped = []
    now = now_ist_naive()
    for o in orders:
        available = None
        if o.catalog_medicine_id:
            catalog_item = db.query(HospitalMedicine).filter(HospitalMedicine.id == o.catalog_medicine_id).first()
            if catalog_item and catalog_item.stock_quantity is not None:
                available = catalog_item.stock_quantity

        billable_qty = min(o.quantity, available) if available is not None else o.quantity

        if billable_qty <= 0:
            skipped.append(o.medicine_name)
            continue

        o.billed_quantity = billable_qty
        o.status = "paid"
        o.paid_at = now
        o.queued_at = now
        total += o.unit_price * billable_qty
        charged_count += 1

    db.commit()

    log_action(
        db, current_doctor,
        action="medicine_fees_collected",
        target_type="consultation",
        target_id=consultation.id,
        target_label=f"Rs.{total:.2f} for {charged_count} medicines" + (f" ({len(skipped)} skipped — out of stock)" if skipped else ""),
        hospital_id=current_doctor.hospital_id
    )
    return {"charged": total, "count": charged_count, "skipped": skipped}

@router.get("/pending-tasks")
def search_pending_pharmacy_tasks(
    q: str = "",
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Paid-but-not-dispensed medicines that fell out of today's queue,
    grouped by patient. With no query, lists everything pending; with a
    query (2+ chars), filters to matching patients. Free, repeatable
    requeue, as long as still inside the order's window."""
    require_pharmacy(current_doctor)

    today = ist_today()

    orders_query = db.query(MedicineOrder).join(
        Patient, MedicineOrder.patient_id == Patient.id
    ).filter(
        MedicineOrder.hospital_id == current_doctor.hospital_id,
        MedicineOrder.status == "paid"
    )
    if q and len(q.strip()) >= 2:
        like = f"%{q.strip()}%"
        orders_query = orders_query.filter(
            (Patient.name.ilike(like)) | (Patient.patient_uid.ilike(like))
        )

    by_patient = {}
    for o in orders_query.all():
        if o.queued_at and o.queued_at.date() == today:
            continue
        if is_order_expired(db, o.patient_id, o.consultation_id, o.created_at):
            continue
        by_patient.setdefault(o.patient_id, []).append(o)

    if not by_patient:
        return []

    patients = db.query(Patient).filter(Patient.id.in_(by_patient.keys())).all()
    patient_map = {p.id: p for p in patients}

    result = []
    for patient_id, orders_list in by_patient.items():
        p = patient_map.get(patient_id)
        if not p:
            continue
        pending = []
        for o in orders_list:
            consultation = db.query(Consultation).filter(Consultation.id == o.consultation_id).first()
            ordering_doctor = db.query(Doctor).filter(Doctor.id == consultation.doctor_id).first() if consultation else None
            pending.append({
                "order_id": o.id,
                "medicine_name": o.medicine_name,
                "quantity": o.quantity,
                "doctor_name": f"{ordering_doctor.title} {ordering_doctor.name}" if ordering_doctor else "—",
                "paid_at": o.paid_at.isoformat() if o.paid_at else None,
                "token_number": consultation.token_number if consultation else None
            })
        result.append({
            "patient_id": p.id,
            "patient_name": p.name,
            "patient_uid": p.patient_uid,
            "pending": pending
        })
    return result


@router.post("/pending-tasks/{patient_id}/requeue-all")
def requeue_all_for_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Requeue every currently-pending (paid, not-yet-dispensed, not expired)
    medicine order for one patient in a single action, rather than one
    order at a time."""
    require_pharmacy(current_doctor)

    patient = db.query(Patient).filter(
        Patient.id == patient_id,
        Patient.hospital_id == current_doctor.hospital_id
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    today = ist_today()
    orders = db.query(MedicineOrder).filter(
        MedicineOrder.patient_id == patient_id,
        MedicineOrder.hospital_id == current_doctor.hospital_id,
        MedicineOrder.status == "paid"
    ).all()

    requeued_ids = []
    for o in orders:
        if o.queued_at and o.queued_at.date() == today:
            continue
        if is_order_expired(db, o.patient_id, o.consultation_id, o.created_at):
            continue
        o.queued_at = now_ist_naive()
        requeued_ids.append(o.id)

    if not requeued_ids:
        raise HTTPException(status_code=400, detail="Nothing to requeue for this patient")

    db.commit()

    log_action(
        db, current_doctor,
        action="medicine_order_requeued",
        target_type="patient",
        target_id=patient.id,
        target_label=f"{patient.name} — {len(requeued_ids)} medicine(s)",
        hospital_id=current_doctor.hospital_id
    )
    return {"patient_id": patient.id, "count": len(requeued_ids), "order_ids": requeued_ids}


class AddMedicineIn(BaseModel):
    catalog_medicine_id: int
    quantity: int = 1
    substitute_for_id: Optional[int] = None


@router.post("/prescription/{token_number}/add-medicine")
def add_medicine_order(
    token_number: str,
    payload: AddMedicineIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_pharmacy(current_doctor)
    require_present(db, current_doctor)

    consultation = db.query(Consultation).filter(
        Consultation.token_number == token_number,
        Consultation.is_voided == False
    ).first()
    if not consultation:
        raise HTTPException(status_code=404, detail="Prescription not found")

    catalog_item = db.query(HospitalMedicine).filter(
        HospitalMedicine.id == payload.catalog_medicine_id,
        HospitalMedicine.hospital_id == current_doctor.hospital_id,
        HospitalMedicine.is_active == True
    ).first()
    if not catalog_item:
        raise HTTPException(status_code=404, detail="Catalog medicine not found")

    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than 0")

    dosage_form_warning = None
    if payload.substitute_for_id:
        original = db.query(MedicineOrder).filter(
            MedicineOrder.id == payload.substitute_for_id,
            MedicineOrder.consultation_id == consultation.id
        ).first()
        if not original:
            raise HTTPException(status_code=404, detail="Original medicine order not found")
        if original.status != "advised":
            raise HTTPException(status_code=400, detail="Cannot substitute — original medicine already resolved")

        # Substitution is brand-only, never a different active ingredient
        # without the doctor's explicit sign-off — verified against the
        # catalog, not free-text names, so both sides must be linked.
        if not original.catalog_medicine_id:
            raise HTTPException(
                status_code=400,
                detail="Link the original order to a catalog medicine first (via link-catalog) so its salt/strength can be verified before substituting."
            )
        original_catalog = db.query(HospitalMedicine).filter(HospitalMedicine.id == original.catalog_medicine_id).first()
        if not original_catalog:
            raise HTTPException(status_code=400, detail="Original catalog medicine not found — cannot verify substitution safety")

        original_generic = _generic_identity(db, original.catalog_medicine_id)
        replacement_generic = _generic_identity(db, catalog_item.id)
        if not original_generic or (original_generic or "").strip().lower() != (replacement_generic or "").strip().lower():
            raise HTTPException(
                status_code=400,
                detail=f"Substitution blocked — {catalog_item.generic_name} is a different active ingredient than {original_catalog.generic_name}. Brand-only substitution is allowed; a different salt needs the doctor's explicit sign-off."
            )
        if (original_catalog.strength or "").strip().lower() != (catalog_item.strength or "").strip().lower():
            raise HTTPException(
                status_code=400,
                detail=f"Substitution blocked — strength mismatch ({original_catalog.strength or 'unspecified'} vs {catalog_item.strength or 'unspecified'})."
            )
        if (original_catalog.dosage_forms or "").strip().lower() != (catalog_item.dosage_forms or "").strip().lower():
            dosage_form_warning = f"Dosage form differs from the original ({original_catalog.dosage_forms or 'unspecified'} vs {catalog_item.dosage_forms or 'unspecified'}) — double-check this is appropriate."

        original.included = False

    new_order = MedicineOrder(
        consultation_id=consultation.id,
        patient_id=consultation.patient_id,
        hospital_id=current_doctor.hospital_id,
        catalog_medicine_id=catalog_item.id,
        medicine_name=catalog_item.generic_name,
        brand_name=catalog_item.brand_name,
        unit_price=catalog_item.price,
        quantity=payload.quantity,
        included=True,
        status="advised",
        substitute_for_id=payload.substitute_for_id
    )
    db.add(new_order)
    db.commit()
    db.refresh(new_order)

    log_action(
        db, current_doctor,
        action="medicine_order_added",
        target_type="consultation",
        target_id=consultation.id,
        target_label=f"Added {new_order.medicine_name}" + (" (substitute)" if payload.substitute_for_id else ""),
        hospital_id=current_doctor.hospital_id
    )

    result = serialize_medicine_order(new_order, db)
    if dosage_form_warning:
        result["warning"] = dosage_form_warning
    return result


@router.post("/prescription/{token_number}/dispense")
def dispense_prescription(
    token_number: str,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """The REAL in-hospital dispense action — deducts actual stock via FEFO
    batches. Do not confuse with /consultations/verify/{token}/dispense,
    which is the public third-party-pharmacy endpoint and must never touch
    stock."""
    require_pharmacy(current_doctor)
    require_present(db, current_doctor)

    consultation = db.query(Consultation).filter(
        Consultation.token_number == token_number,
        Consultation.is_voided == False
    ).first()
    if not consultation:
        raise HTTPException(status_code=404, detail="Prescription not found")
    if consultation.is_dispensed:
        raise HTTPException(status_code=400, detail="Already marked as dispensed")

    from app.utils.inventory import deduct_stock_fefo

    paid_orders = db.query(MedicineOrder).filter(
        MedicineOrder.consultation_id == consultation.id,
        MedicineOrder.status == "paid"
    ).all()

    for o in paid_orders:
        block_reason = _schedule_x_repeat_block(db, o)
        if block_reason:
            raise HTTPException(status_code=400, detail=block_reason)

    for o in paid_orders:
        if o.catalog_medicine_id and o.billed_quantity:
            deduct_stock_fefo(db, o.catalog_medicine_id, o.billed_quantity)
        o.status = "dispensed"
        o.dispensed_at = now_ist_naive()
        o.dispensed_by = current_doctor.id

        medicine = db.query(HospitalMedicine).filter(HospitalMedicine.id == o.catalog_medicine_id).first() if o.catalog_medicine_id else None
        if medicine and medicine.schedule == "x":
            log_action(
                db, current_doctor,
                action="schedule_x_dispensed",
                target_type="medicine_order",
                target_id=o.id,
                target_label=o.medicine_name,
                details=json.dumps({
                    "patient_id": o.patient_id,
                    "quantity": o.billed_quantity,
                    "repeat": o.repeat_authorized,
                    "repeat_authorized_by": o.repeat_authorized_by,
                }),
                hospital_id=current_doctor.hospital_id
            )

    consultation.is_dispensed = True
    consultation.dispensed_at = now_ist_naive()
    db.commit()

    from app.utils.notify import sync_stock_notifications
    sync_stock_notifications(db, current_doctor.hospital_id)

    log_action(
        db, current_doctor,
        action="prescription_dispensed",
        target_type="consultation",
        target_id=consultation.id,
        target_label=f"{token_number} (in-hospital — stock deducted)",
        hospital_id=current_doctor.hospital_id
    )
    return {"message": "Dispensed and stock deducted", "dispensed_at": consultation.dispensed_at.isoformat()}


@router.patch("/medicine-orders/{order_id}/mark-unavailable")
def mark_medicine_order_unavailable(
    order_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_pharmacy(current_doctor)
    require_present(db, current_doctor)

    order = db.query(MedicineOrder).filter(
        MedicineOrder.id == order_id,
        MedicineOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Medicine order not found")
    if order.status != "advised":
        raise HTTPException(status_code=400, detail="Cannot change after payment")

    order.status = "unavailable"
    order.included = False
    db.commit()

    log_action(
        db, current_doctor,
        action="medicine_order_unavailable",
        target_type="medicine_order",
        target_id=order.id,
        target_label=f"{order.medicine_name} — advised outside",
        hospital_id=current_doctor.hospital_id
    )
    return serialize_medicine_order(order, db)


@router.post("/medicine-orders/{order_id}/requeue")
def requeue_medicine_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_pharmacy(current_doctor)

    order = db.query(MedicineOrder).filter(
        MedicineOrder.id == order_id,
        MedicineOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Medicine order not found")
    if order.status != "paid":
        raise HTTPException(status_code=400, detail="Only paid, undispensed medicines can be requeued")
    if is_order_expired(db, order.patient_id, order.consultation_id, order.created_at):
        raise HTTPException(status_code=400, detail="This order's window has closed — a fresh order is needed")

    order.queued_at = now_ist_naive()
    db.commit()

    log_action(
        db, current_doctor,
        action="medicine_order_requeued",
        target_type="medicine_order",
        target_id=order.id,
        target_label=order.medicine_name,
        hospital_id=current_doctor.hospital_id
    )
    return {"id": order.id, "queued_at": order.queued_at.isoformat()}


class ReturnMedicineOrderIn(BaseModel):
    quantity: int
    disposition: str  # "returned_to_supplier" | "sent_to_disposal" | "restocked_to_shelf"
    channel: str       # "cash" | "card" | "upi" | "online" — how the refund is issued
    note: Optional[str] = None


@router.post("/medicine-orders/{order_id}/return")
def return_medicine_order(
    order_id: int,
    body: ReturnMedicineOrderIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """OPD return — patient paid the hospital pharmacy directly, so this
    issues a real Refund (unlike the IPD path, which just credits the
    running admission bill). Stock only ever moves back up on the explicit,
    deliberate restocked_to_shelf choice — never as a default, never for
    returned_to_supplier or sent_to_disposal."""
    require_pharmacy(current_doctor)

    order = db.query(MedicineOrder).filter(
        MedicineOrder.id == order_id,
        MedicineOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Medicine order not found")
    if order.status != "dispensed":
        raise HTTPException(status_code=400, detail="Only a dispensed medicine can be returned")
    if body.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than zero")
    if body.disposition not in ("returned_to_supplier", "sent_to_disposal", "restocked_to_shelf"):
        raise HTTPException(status_code=400, detail="disposition must be 'returned_to_supplier', 'sent_to_disposal', or 'restocked_to_shelf'")
    if body.channel not in VALID_CHANNELS:
        raise HTTPException(status_code=400, detail="Invalid channel")

    dispensed_qty = order.billed_quantity or order.quantity or 0
    already_returned = sum(r.quantity for r in db.query(MedicineOrderReturn).filter(MedicineOrderReturn.order_id == order.id).all())
    available_to_return = dispensed_qty - already_returned
    if body.quantity > available_to_return:
        raise HTTPException(status_code=400, detail=f"Only {available_to_return} unit(s) from this order are eligible for return")

    # Stock only moves back up on this one explicit, deliberate choice.
    if body.disposition == "restocked_to_shelf" and order.catalog_medicine_id:
        catalog_item = db.query(HospitalMedicine).filter(HospitalMedicine.id == order.catalog_medicine_id).first()
        if catalog_item:
            catalog_item.stock_quantity = (catalog_item.stock_quantity or 0) + body.quantity

    refund_amount = (order.unit_price or 0) * body.quantity

    refund = Refund(
        patient_id=order.patient_id,
        hospital_id=order.hospital_id,
        source_type="pharmacy",
        source_id=order.id,
        amount=refund_amount,
        channel=body.channel,
        status="pending" if body.channel == "online" else "completed",
        reason=f"Pharmacy return — {order.medicine_name} x{body.quantity}",
        processed_by=current_doctor.id,
    )
    db.add(refund)
    db.flush()

    db.add(MedicineOrderReturn(
        order_id=order.id, quantity=body.quantity, disposition=body.disposition,
        note=body.note, refund_id=refund.id, returned_by=current_doctor.id, returned_at=now_ist_naive(),
    ))
    db.commit()

    log_action(
        db, current_doctor,
        action="medicine_order_returned",
        target_type="medicine_order",
        target_id=order.id,
        target_label=f"{order.medicine_name} x{body.quantity} ({body.disposition})",
        hospital_id=current_doctor.hospital_id
    )
    return {"message": "Return recorded", "refunded_amount": refund_amount, "refund_status": refund.status}


@router.patch("/medicine-orders/{order_id}/authorize-repeat")
def authorize_schedule_x_repeat(
    order_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Doctor sign-off required before a Schedule X repeat can be dispensed —
    locked to the original prescriber (via the order's consultation), since
    an unlocked narcotic-repeat authorization defeats the point of requiring
    sign-off at all. admin/sub_admin can still override for genuine
    unavailability (doctor transferred/off duty/resigned), but that path
    logs under a distinct action so it's never silently indistinguishable
    from the normal same-prescriber case in the audit trail."""
    order = db.query(MedicineOrder).filter(
        MedicineOrder.id == order_id,
        MedicineOrder.hospital_id == current_doctor.hospital_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Medicine order not found")

    medicine = db.query(HospitalMedicine).filter(HospitalMedicine.id == order.catalog_medicine_id).first() if order.catalog_medicine_id else None
    if not medicine or medicine.schedule != "x":
        raise HTTPException(status_code=400, detail="This order isn't a Schedule X item")

    consultation = db.query(Consultation).filter(Consultation.id == order.consultation_id).first()
    prescriber_id = consultation.doctor_id if consultation else None

    is_admin_override = False
    if current_doctor.id == prescriber_id:
        pass  # normal case — original prescriber authorizing their own order
    elif current_doctor.role.value in ["admin", "sub_admin"]:
        is_admin_override = True
    else:
        prescriber = db.query(Doctor).filter(Doctor.id == prescriber_id).first() if prescriber_id else None
        prescriber_label = f"{prescriber.title} {prescriber.name}" if prescriber else "the original prescriber"
        raise HTTPException(status_code=403, detail=f"Only {prescriber_label}, who originally prescribed this, can authorize a repeat.")

    order.repeat_authorized = True
    order.repeat_authorized_by = current_doctor.id
    order.repeat_authorized_at = now_ist_naive()
    db.commit()

    log_action(
        db, current_doctor,
        action="schedule_x_repeat_authorized_by_admin_override" if is_admin_override else "schedule_x_repeat_authorized",
        target_type="medicine_order",
        target_id=order.id,
        target_label=order.medicine_name,
        details=json.dumps({"patient_id": order.patient_id, "original_prescriber_id": prescriber_id}),
        hospital_id=current_doctor.hospital_id
    )
    return {"message": "Repeat dispense authorized", "authorized_at": order.repeat_authorized_at.isoformat()}


@router.get("/schedule-x-register")
def schedule_x_register(
    start_date: date = None,
    end_date: date = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Schedule X (narcotics/high-abuse-potential) dispensing register — the
    tightest audit trail of the three tiers: who authorized it, who
    dispensed it, when. Same MedicineOrder-backed approach as the H1
    register; nothing here gets bulk-deleted, comfortably past the
    legally-required 2-year retention."""
    require_pharmacy(current_doctor)

    q = db.query(MedicineOrder).join(
        HospitalMedicine, MedicineOrder.catalog_medicine_id == HospitalMedicine.id
    ).filter(
        MedicineOrder.hospital_id == current_doctor.hospital_id,
        HospitalMedicine.schedule == "x",
        MedicineOrder.status == "dispensed",
        MedicineOrder.included == True,  # noqa: E712
        MedicineOrder.dispensed_at.isnot(None),
    )
    if start_date:
        q = q.filter(MedicineOrder.dispensed_at >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        q = q.filter(MedicineOrder.dispensed_at < datetime.combine(end_date, datetime.max.time()))

    orders = q.order_by(MedicineOrder.dispensed_at.desc()).all()

    result = []
    for o in orders:
        consultation = db.query(Consultation).filter(Consultation.id == o.consultation_id).first()
        patient = db.query(Patient).filter(Patient.id == o.patient_id).first()
        prescriber = db.query(Doctor).filter(Doctor.id == consultation.doctor_id).first() if consultation else None
        pharmacist = db.query(Doctor).filter(Doctor.id == o.dispensed_by).first() if o.dispensed_by else None
        authorizer = db.query(Doctor).filter(Doctor.id == o.repeat_authorized_by).first() if o.repeat_authorized_by else None
        result.append({
            "id": o.id,
            "date": o.dispensed_at.isoformat() if o.dispensed_at else None,
            "patient_name": patient.name if patient else None,
            "prescribing_doctor": f"{prescriber.title} {prescriber.name}" if prescriber else None,
            "medicine_name": o.medicine_name,
            "brand_name": o.brand_name,
            "quantity": o.billed_quantity or o.quantity,
            "dispensing_pharmacist": f"{pharmacist.title} {pharmacist.name}" if pharmacist else "Unrecorded (dispensed before this register was added)",
            "is_repeat": o.repeat_authorized,
            "repeat_authorized_by": f"{authorizer.title} {authorizer.name}" if authorizer else None,
            "repeat_authorized_at": o.repeat_authorized_at.isoformat() if o.repeat_authorized_at else None,
        })
    return {"count": len(result), "entries": result}


@router.get("/medicine-orders/schedule-x-status/{consultation_id}")
def schedule_x_status_for_consultation(
    consultation_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Doctor-facing visibility into this consultation's Schedule X orders —
    lets a doctor see and authorize a repeat from their own patient-history
    screen, not just from the pharmacy page. Deliberately scoped to Schedule
    X status only (not full pharmacy/dispense data), since doctors otherwise
    have no access to MedicineOrder records at all — this isn't a general
    pharmacy read grant, just enough for this one action."""
    consultation = db.query(Consultation).filter(Consultation.id == consultation_id).first()
    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found")
    patient = db.query(Patient).filter(
        Patient.id == consultation.patient_id,
        Patient.hospital_id == current_doctor.hospital_id
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Consultation not found")

    orders = db.query(MedicineOrder).join(
        HospitalMedicine, MedicineOrder.catalog_medicine_id == HospitalMedicine.id
    ).filter(
        MedicineOrder.consultation_id == consultation_id,
        HospitalMedicine.schedule == "x",
        MedicineOrder.included == True,  # noqa: E712
    ).all()

    result = []
    for o in orders:
        result.append({
            "id": o.id,
            "medicine_name": o.medicine_name,
            "status": o.status,
            "repeat_authorized": o.repeat_authorized,
        })
    return {"orders": result}


@router.get("/schedule-h1-register")
def schedule_h1_register(
    start_date: date = None,
    end_date: date = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Schedule H1 dispensing register — the digital equivalent of the
    physical register pharmacies are legally required to keep for H1 drugs
    (antibiotics, anti-TB, certain psychotropics). Built on real MedicineOrder
    dispense records rather than a separate table, since every field the
    register needs — patient, prescribing doctor, medicine, quantity,
    dispensing pharmacist, date — already lives there once dispensed.
    Nothing in this codebase bulk-deletes MedicineOrder rows, so this stays
    queryable indefinitely, well past the legally-required 3 years."""
    require_pharmacy(current_doctor)

    q = db.query(MedicineOrder).join(
        HospitalMedicine, MedicineOrder.catalog_medicine_id == HospitalMedicine.id
    ).filter(
        MedicineOrder.hospital_id == current_doctor.hospital_id,
        HospitalMedicine.schedule == "h1",
        MedicineOrder.status == "dispensed",
        MedicineOrder.included == True,  # noqa: E712 — never surface a substituted-out original alongside its replacement
        MedicineOrder.dispensed_at.isnot(None),
    )
    if start_date:
        q = q.filter(MedicineOrder.dispensed_at >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        q = q.filter(MedicineOrder.dispensed_at < datetime.combine(end_date, datetime.max.time()))

    orders = q.order_by(MedicineOrder.dispensed_at.desc()).all()

    result = []
    for o in orders:
        consultation = db.query(Consultation).filter(Consultation.id == o.consultation_id).first()
        patient = db.query(Patient).filter(Patient.id == o.patient_id).first()
        prescriber = db.query(Doctor).filter(Doctor.id == consultation.doctor_id).first() if consultation else None
        pharmacist = db.query(Doctor).filter(Doctor.id == o.dispensed_by).first() if o.dispensed_by else None
        result.append({
            "id": o.id,
            "date": o.dispensed_at.isoformat() if o.dispensed_at else None,
            "patient_name": patient.name if patient else None,
            "prescribing_doctor": f"{prescriber.title} {prescriber.name}" if prescriber else None,
            "medicine_name": o.medicine_name,
            "brand_name": o.brand_name,
            "quantity": o.billed_quantity or o.quantity,
            "dispensing_pharmacist": f"{pharmacist.title} {pharmacist.name}" if pharmacist else "Unrecorded (dispensed before this register was added)",
        })
    return {"count": len(result), "entries": result}