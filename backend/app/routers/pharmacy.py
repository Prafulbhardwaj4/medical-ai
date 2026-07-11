from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import date, datetime
import json

from pydantic import BaseModel
from datetime import datetime
from app.database import get_db
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.consultation import Consultation
from app.models.medicine_order import MedicineOrder
from app.models.hospital_medicine import HospitalMedicine
from app.utils.auth import get_current_doctor
from app.utils.audit import log_action
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

    today_start = datetime.combine(date.today(), datetime.min.time())
    today_end = datetime.combine(date.today(), datetime.max.time())

    rows = (
        db.query(Consultation, Patient)
        .join(Patient, Consultation.patient_id == Patient.id)
        .filter(
            Patient.hospital_id == current_doctor.hospital_id,
            Consultation.token_number != None,
            Consultation.is_voided == False,
            Consultation.created_at >= today_start,
            Consultation.created_at <= today_end
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
        "medicine_orders": [serialize_medicine_order(m) for m in medicine_orders],
        "is_dispensed": consultation.is_dispensed,
        "dispensed_at": consultation.dispensed_at.isoformat() if consultation.dispensed_at else None,
        "verify_hash": consultation.verify_hash
    }


def serialize_medicine_order(m: MedicineOrder):
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
        "line_total": (m.unit_price * m.quantity) if (m.unit_price is not None and m.quantity is not None) else None,
        "included": m.included,
        "status": m.status
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
    return serialize_medicine_order(order)


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
    return serialize_medicine_order(order)


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
    for o in orders:
        o.status = "paid"
        o.paid_at = datetime.utcnow()
        total += o.unit_price * o.quantity

    db.commit()

    log_action(
        db, current_doctor,
        action="medicine_fees_collected",
        target_type="consultation",
        target_id=consultation.id,
        target_label=f"₹{total} for {len(orders)} medicines",
        hospital_id=current_doctor.hospital_id
    )
    return {"charged": total, "count": len(orders)}