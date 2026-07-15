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
from app.models.hospital_medicine import HospitalMedicine
from app.utils.auth import get_current_doctor, ist_today, ist_day_bounds_utc
from app.utils.audit import log_action
from app.utils.order_lifecycle import is_order_expired
from app.routers.attendance import require_present

router = APIRouter(prefix="/pharmacy", tags=["pharmacy"])


def require_pharmacy(current_doctor: Doctor):
    if current_doctor.role.value not in ["pharmacy", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")


@router.get("/queue")
def get_pharmacy_queue(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_pharmacy(current_doctor)

    today_start, today_end = ist_day_bounds_utc()

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
    if db is not None and m.catalog_medicine_id:
        catalog_item = db.query(HospitalMedicine).filter(HospitalMedicine.id == m.catalog_medicine_id).first()
        if catalog_item:
            stock_quantity = catalog_item.stock_quantity
            low_stock_threshold = catalog_item.low_stock_threshold

    billed = m.billed_quantity if m.billed_quantity is not None else m.quantity
    return {
        "id": m.id,
        "medicine_name": m.medicine_name,
        "brand_name": m.brand_name or "",
        "dosage": m.dosage or "",
        "frequency": m.frequency or "",
        "duration": m.duration or "",
        "catalog_medicine_id": m.catalog_medicine_id,
        "unit_price": m.unit_price,
        "quantity": m.quantity,
        "billed_quantity": m.billed_quantity,
        "line_total": (m.unit_price * billed) if (m.unit_price is not None and billed is not None) else None,
        "included": m.included,
        "status": m.status,
        "substitute_for_id": m.substitute_for_id,
        "stock_quantity": stock_quantity,
        "low_stock_threshold": low_stock_threshold
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
    if order.status != "advised":
        raise HTTPException(status_code=400, detail="Cannot change inclusion after payment")

    order.included = not order.included
    db.commit()
    return {"id": order.id, "included": order.included}


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
        query = query.filter(HospitalMedicine.generic_name.ilike(like) | HospitalMedicine.brand_names.ilike(like))

    items = query.order_by(HospitalMedicine.generic_name).limit(20).all()
    return [
        {"id": m.id, "generic_name": m.generic_name, "brand_names": m.brand_names or "", "price": m.price, "strength": m.strength or ""}
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

    total = 0
    charged_count = 0
    skipped = []
    now = datetime.utcnow()
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
        target_label=f"Rs.{total} for {charged_count} medicines" + (f" ({len(skipped)} skipped — out of stock)" if skipped else ""),
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
        o.queued_at = datetime.utcnow()
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

    if payload.substitute_for_id:
        original = db.query(MedicineOrder).filter(
            MedicineOrder.id == payload.substitute_for_id,
            MedicineOrder.consultation_id == consultation.id
        ).first()
        if not original:
            raise HTTPException(status_code=404, detail="Original medicine order not found")

    new_order = MedicineOrder(
        consultation_id=consultation.id,
        patient_id=consultation.patient_id,
        hospital_id=current_doctor.hospital_id,
        catalog_medicine_id=catalog_item.id,
        medicine_name=catalog_item.generic_name,
        brand_name=catalog_item.brand_names,
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

    return serialize_medicine_order(new_order, db)


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

    order.queued_at = datetime.utcnow()
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