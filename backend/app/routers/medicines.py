from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional
from pydantic import BaseModel
from datetime import date, datetime, timedelta
import io

from app.database import get_db
from app.models.doctor import Doctor
from app.models.hospital_medicine import HospitalMedicine
from app.models.medicine_batch import MedicineBatch
from app.utils.auth import get_current_doctor, ist_today
from app.utils.audit import log_action
from app.services.groq_service import extract_medicines
from app.utils.notify import sync_stock_notifications

router = APIRouter(prefix="/admin/medicines", tags=["medicines"])

VALID_SCHEDULES = {"otc", "h", "h1", "x"}


def require_admin(current_doctor: Doctor):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")


def require_admin_or_pharmacy(current_doctor: Doctor):
    # Stock viewing/adding is an operational pharmacy task, not catalog curation —
    # pharmacy can view and add stock, but cannot create/edit/deactivate medicines.
    if current_doctor.role.value not in ["admin", "sub_admin", "pharmacy"]:
        raise HTTPException(status_code=403, detail="Not authorized")


class MedicineIn(BaseModel):
    generic_name: str
    brand_names: Optional[str] = ""
    category: Optional[str] = ""
    dosage_forms: Optional[str] = ""
    strength: Optional[str] = ""
    schedule: Optional[str] = "otc"
    low_stock_threshold: Optional[int] = 25
    pack_size: Optional[int] = 1
    price_per_pack: Optional[float] = None
    billing_mode: Optional[str] = "per_unit"
    gst_percent: Optional[float] = None


VALID_BILLING_MODES = {"per_unit", "per_pack"}


def compute_unit_price(price_per_pack, pack_size):
    if price_per_pack is None or not pack_size or pack_size < 1:
        return None
    return round(price_per_pack / pack_size, 2)


class MedicineBulkConfirm(BaseModel):
    medicines: list[MedicineIn]


class BrandIn(BaseModel):
    brand_name: str
    price_per_pack: Optional[float] = None
    low_stock_threshold: Optional[int] = None


def serialize(m: HospitalMedicine):
    return {
        "id": m.id,
        "generic_name": m.generic_name,
        "brand_names": m.brand_names or "",
        "brand_name": m.brand_name or "",
        "parent_medicine_id": m.parent_medicine_id,
        "category": m.category or "",
        "dosage_forms": m.dosage_forms or "",
        "strength": m.strength or "",
        "schedule": m.schedule,
        "low_stock_threshold": m.low_stock_threshold,
        "pack_size": m.pack_size,
        "price_per_pack": m.price_per_pack,
        "billing_mode": m.billing_mode,
        "gst_percent": m.gst_percent,
        "price": m.price,  # computed unit price
        "stock_quantity": m.stock_quantity,
        "is_active": m.is_active
    }


@router.get("")
def list_medicines(
    category: Optional[str] = None,
    schedule: Optional[str] = None,
    dosage_form: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin_or_pharmacy(current_doctor)

    query = db.query(HospitalMedicine).filter(
        HospitalMedicine.hospital_id == current_doctor.hospital_id,
        HospitalMedicine.is_active == True
    )

    if category:
        query = query.filter(HospitalMedicine.category == category)
    if schedule:
        query = query.filter(HospitalMedicine.schedule == schedule)
    if dosage_form:
        query = query.filter(HospitalMedicine.dosage_forms == dosage_form)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(
            HospitalMedicine.generic_name.ilike(like),
            HospitalMedicine.brand_names.ilike(like),
            HospitalMedicine.brand_name.ilike(like)
        ))

    items = query.order_by(HospitalMedicine.generic_name).all()
    return [serialize(m) for m in items]


@router.post("", status_code=201)
def create_medicine(
    payload: MedicineIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin_or_pharmacy(current_doctor)

    schedule = (payload.schedule or "otc").lower()
    if schedule not in VALID_SCHEDULES:
        raise HTTPException(status_code=400, detail="Invalid schedule")

    billing_mode = (payload.billing_mode or "per_unit").lower()
    if billing_mode not in VALID_BILLING_MODES:
        raise HTTPException(status_code=400, detail="Invalid billing mode")

    pack_size = payload.pack_size or 1
    if pack_size < 1:
        raise HTTPException(status_code=400, detail="Pack size must be at least 1")

    medicine = HospitalMedicine(
        hospital_id=current_doctor.hospital_id,
        generic_name=payload.generic_name.strip(),
        brand_names=(payload.brand_names or "").strip(),
        category=(payload.category or "").strip(),
        dosage_forms=(payload.dosage_forms or "").strip(),
        strength=(payload.strength or "").strip(),
        schedule=schedule,
        low_stock_threshold=payload.low_stock_threshold or 25,
        pack_size=pack_size,
        price_per_pack=payload.price_per_pack,
        billing_mode=billing_mode,
        gst_percent=payload.gst_percent,
        price=compute_unit_price(payload.price_per_pack, pack_size),
        stock_quantity=0,
        is_active=True
    )
    db.add(medicine)
    db.commit()
    db.refresh(medicine)

    log_action(
        db, current_doctor,
        action="medicine_created",
        target_type="hospital_medicine",
        target_id=medicine.id,
        target_label=medicine.generic_name,
        hospital_id=current_doctor.hospital_id
    )
    return serialize(medicine)


@router.post("/{medicine_id}/brands", status_code=201)
def add_medicine_brand(
    medicine_id: int,
    payload: BrandIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin_or_pharmacy(current_doctor)

    parent = db.query(HospitalMedicine).filter(
        HospitalMedicine.id == medicine_id,
        HospitalMedicine.hospital_id == current_doctor.hospital_id
    ).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Medicine not found")

    brand_name = (payload.brand_name or "").strip()
    if not brand_name:
        raise HTTPException(status_code=400, detail="Brand name is required")

    root_id = parent.parent_medicine_id or parent.id
    existing = db.query(HospitalMedicine).filter(
        HospitalMedicine.hospital_id == current_doctor.hospital_id,
        or_(HospitalMedicine.id == root_id, HospitalMedicine.parent_medicine_id == root_id),
        HospitalMedicine.brand_name.ilike(brand_name)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"'{brand_name}' already exists for this medicine")

    root = db.query(HospitalMedicine).filter(HospitalMedicine.id == root_id).first()

    brand_row = HospitalMedicine(
        hospital_id=current_doctor.hospital_id,
        generic_name=root.generic_name,
        category=root.category,
        dosage_forms=root.dosage_forms,
        strength=root.strength,
        schedule=root.schedule,
        brand_name=brand_name,
        parent_medicine_id=root.id,
        low_stock_threshold=payload.low_stock_threshold or root.low_stock_threshold or 25,
        pack_size=root.pack_size,
        price_per_pack=payload.price_per_pack,
        billing_mode=root.billing_mode,
        gst_percent=root.gst_percent,
        price=compute_unit_price(payload.price_per_pack, root.pack_size),
        stock_quantity=0,
        is_active=True
    )
    db.add(brand_row)
    db.commit()
    db.refresh(brand_row)

    log_action(
        db, current_doctor,
        action="medicine_brand_added",
        target_type="hospital_medicine",
        target_id=brand_row.id,
        target_label=f"{root.generic_name} — {brand_name}",
        hospital_id=current_doctor.hospital_id
    )
    return serialize(brand_row)


@router.patch("/{medicine_id}")
def update_medicine(
    medicine_id: int,
    payload: MedicineIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin(current_doctor)

    medicine = db.query(HospitalMedicine).filter(
        HospitalMedicine.id == medicine_id,
        HospitalMedicine.hospital_id == current_doctor.hospital_id
    ).first()
    if not medicine:
        raise HTTPException(status_code=404, detail="Medicine not found")

    schedule = (payload.schedule or "otc").lower()
    if schedule not in VALID_SCHEDULES:
        raise HTTPException(status_code=400, detail="Invalid schedule")

    billing_mode = (payload.billing_mode or "per_unit").lower()
    if billing_mode not in VALID_BILLING_MODES:
        raise HTTPException(status_code=400, detail="Invalid billing mode")

    pack_size = payload.pack_size or 1
    if pack_size < 1:
        raise HTTPException(status_code=400, detail="Pack size must be at least 1")

    medicine.generic_name = payload.generic_name.strip()
    medicine.brand_names = (payload.brand_names or "").strip()
    medicine.category = (payload.category or "").strip()
    medicine.dosage_forms = (payload.dosage_forms or "").strip()
    medicine.strength = (payload.strength or "").strip()
    medicine.schedule = schedule
    medicine.low_stock_threshold = payload.low_stock_threshold or 25
    medicine.pack_size = pack_size
    medicine.price_per_pack = payload.price_per_pack
    medicine.billing_mode = billing_mode
    medicine.gst_percent = payload.gst_percent
    medicine.price = compute_unit_price(payload.price_per_pack, pack_size)
    # stock_quantity is deliberately NOT touched here — it's owned exclusively
    # by the batch endpoints (add/edit/delete batch). Editing catalog details
    # must never affect live stock.
    db.commit()

    log_action(
        db, current_doctor,
        action="medicine_updated",
        target_type="hospital_medicine",
        target_id=medicine.id,
        target_label=medicine.generic_name,
        hospital_id=current_doctor.hospital_id
    )
    return serialize(medicine)


@router.delete("/{medicine_id}")
def deactivate_medicine(
    medicine_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin(current_doctor)

    medicine = db.query(HospitalMedicine).filter(
        HospitalMedicine.id == medicine_id,
        HospitalMedicine.hospital_id == current_doctor.hospital_id
    ).first()
    if not medicine:
        raise HTTPException(status_code=404, detail="Medicine not found")

    medicine.is_active = False
    db.commit()

    log_action(
        db, current_doctor,
        action="medicine_deactivated",
        target_type="hospital_medicine",
        target_id=medicine.id,
        target_label=medicine.generic_name,
        hospital_id=current_doctor.hospital_id
    )
    return {"id": medicine.id, "is_active": medicine.is_active}


def _extract_text_from_pdf(content: bytes) -> str:
    import pdfplumber
    text_parts = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)


def _extract_text_from_excel(content: bytes) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    lines = []
    for sheet in wb.worksheets:
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None]
            if cells:
                lines.append(", ".join(cells))
    return "\n".join(lines)


@router.post("/upload")
async def upload_medicines(
    file: UploadFile = File(...),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin_or_pharmacy(current_doctor)

    filename = (file.filename or "").lower()
    content = await file.read()

    if filename.endswith(".pdf"):
        raw_text = _extract_text_from_pdf(content)
    elif filename.endswith(".xlsx") or filename.endswith(".xls"):
        raw_text = _extract_text_from_excel(content)
    else:
        raise HTTPException(status_code=400, detail="Only PDF or Excel files are supported")

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract any text from file")

    try:
        extracted = await extract_medicines(raw_text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Extraction failed: {str(e)}")

    return {"medicines": extracted}


@router.post("/bulk-confirm")
def bulk_confirm_medicines(
    payload: MedicineBulkConfirm,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin_or_pharmacy(current_doctor)

    created = []
    for item in payload.medicines:
        schedule = (item.schedule or "otc").lower()
        if schedule not in VALID_SCHEDULES:
            schedule = "h"

        billing_mode = (item.billing_mode or "per_unit").lower()
        if billing_mode not in VALID_BILLING_MODES:
            billing_mode = "per_unit"

        pack_size = item.pack_size or 1
        if pack_size < 1:
            pack_size = 1

        medicine = HospitalMedicine(
            hospital_id=current_doctor.hospital_id,
            generic_name=item.generic_name.strip(),
            brand_names=(item.brand_names or "").strip(),
            category=(item.category or "").strip(),
            dosage_forms=(item.dosage_forms or "").strip(),
            strength=(item.strength or "").strip(),
            schedule=schedule,
            pack_size=pack_size,
            price_per_pack=item.price_per_pack,
            billing_mode=billing_mode,
            gst_percent=item.gst_percent,
            price=compute_unit_price(item.price_per_pack, pack_size),
            stock_quantity=0,
            is_active=True
        )
        db.add(medicine)
        created.append(medicine)

    db.commit()
    for m in created:
        db.refresh(m)

    log_action(
        db, current_doctor,
        action="medicines_bulk_imported",
        target_type="hospital_medicine",
        target_id=0,
        target_label=f"{len(created)} medicines",
        hospital_id=current_doctor.hospital_id
    )
    return [serialize(m) for m in created]

class BatchIn(BaseModel):
    quantity: int
    expiry_date: Optional[date] = None
    batch_number: Optional[str] = ""


def serialize_batch(b: MedicineBatch):
    return {
        "id": b.id,
        "medicine_id": b.medicine_id,
        "batch_number": b.batch_number or "",
        "quantity": b.quantity,
        "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None,
        "received_date": b.received_date.isoformat() if b.received_date else None
    }


@router.post("/{medicine_id}/batches", status_code=201)
def add_batch(
    medicine_id: int,
    payload: BatchIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin_or_pharmacy(current_doctor)

    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than 0")

    medicine = db.query(HospitalMedicine).filter(
        HospitalMedicine.id == medicine_id,
        HospitalMedicine.hospital_id == current_doctor.hospital_id
    ).first()
    if not medicine:
        raise HTTPException(status_code=404, detail="Medicine not found")

    batch_number = (payload.batch_number or "").strip()
    if batch_number:
        duplicate = db.query(MedicineBatch).filter(
            MedicineBatch.medicine_id == medicine_id,
            MedicineBatch.batch_number == batch_number,
            MedicineBatch.quantity > 0
        ).first()
        if duplicate:
            raise HTTPException(status_code=400, detail=f"Batch/Lot '{batch_number}' already exists for this medicine. Edit the existing batch instead, or use a different lot number.")

    batch = MedicineBatch(
        medicine_id=medicine_id,
        hospital_id=current_doctor.hospital_id,
        batch_number=batch_number or None,
        quantity=payload.quantity,
        expiry_date=payload.expiry_date,
        received_date=ist_today()
    )
    db.add(batch)

    medicine.stock_quantity = (medicine.stock_quantity or 0) + payload.quantity
    db.commit()
    db.refresh(batch)
    sync_stock_notifications(db, current_doctor.hospital_id)

    log_action(
        db, current_doctor,
        action="medicine_stock_added",
        target_type="medicine_batch",
        target_id=batch.id,
        target_label=f"{medicine.generic_name} +{payload.quantity}",
        hospital_id=current_doctor.hospital_id
    )
    return serialize_batch(batch)


@router.patch("/batches/{batch_id}")
def edit_batch(
    batch_id: int,
    payload: BatchIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin_or_pharmacy(current_doctor)

    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than 0")

    batch = db.query(MedicineBatch).filter(
        MedicineBatch.id == batch_id,
        MedicineBatch.hospital_id == current_doctor.hospital_id
    ).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    batch_number = (payload.batch_number or "").strip()
    if batch_number:
        duplicate = db.query(MedicineBatch).filter(
            MedicineBatch.medicine_id == batch.medicine_id,
            MedicineBatch.batch_number == batch_number,
            MedicineBatch.id != batch_id,
            MedicineBatch.quantity > 0
        ).first()
        if duplicate:
            raise HTTPException(status_code=400, detail=f"Batch/Lot '{batch_number}' already exists for this medicine.")

    medicine = db.query(HospitalMedicine).filter(HospitalMedicine.id == batch.medicine_id).first()
    if medicine:
        # keep the aggregate stock in sync with the quantity change on this batch
        medicine.stock_quantity = max(0, (medicine.stock_quantity or 0) - batch.quantity + payload.quantity)

    batch.quantity = payload.quantity
    batch.expiry_date = payload.expiry_date
    batch.batch_number = batch_number or None
    db.commit()
    db.refresh(batch)
    sync_stock_notifications(db, current_doctor.hospital_id)

    return serialize_batch(batch)


@router.get("/{medicine_id}/batches")
def list_batches(
    medicine_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin_or_pharmacy(current_doctor)

    batches = db.query(MedicineBatch).filter(
        MedicineBatch.medicine_id == medicine_id,
        MedicineBatch.hospital_id == current_doctor.hospital_id
    ).order_by(MedicineBatch.expiry_date.asc().nullslast()).all()

    return [serialize_batch(b) for b in batches]


@router.delete("/batches/{batch_id}")
def delete_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin_or_pharmacy(current_doctor)

    batch = db.query(MedicineBatch).filter(
        MedicineBatch.id == batch_id,
        MedicineBatch.hospital_id == current_doctor.hospital_id
    ).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    medicine = db.query(HospitalMedicine).filter(HospitalMedicine.id == batch.medicine_id).first()
    if medicine:
        medicine.stock_quantity = max(0, (medicine.stock_quantity or 0) - batch.quantity)

    db.delete(batch)
    db.commit()
    sync_stock_notifications(db, current_doctor.hospital_id)

    return {"deleted": True}


@router.get("/expiring")
def get_expiring_batches(
    within_days: int = 30,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin_or_pharmacy(current_doctor)

    cutoff = ist_today() + timedelta(days=within_days)

    batches = db.query(MedicineBatch).filter(
        MedicineBatch.hospital_id == current_doctor.hospital_id,
        MedicineBatch.expiry_date != None,
        MedicineBatch.expiry_date <= cutoff,
        MedicineBatch.quantity > 0
    ).order_by(MedicineBatch.expiry_date.asc()).all()

    result = []
    for b in batches:
        medicine = db.query(HospitalMedicine).filter(HospitalMedicine.id == b.medicine_id).first()
        if not medicine or not medicine.is_active:
            continue
        days_left = (b.expiry_date - ist_today()).days
        result.append({
            "batch_id": b.id,
            "medicine_id": b.medicine_id,
            "medicine_name": f"{medicine.generic_name}{' ' + medicine.strength if medicine.strength else ''}",
            "batch_number": b.batch_number or "",
            "quantity": b.quantity,
            "expiry_date": b.expiry_date.isoformat(),
            "days_left": days_left,
            "is_expired": days_left < 0
        })
    return result

@router.get("/low-stock")
def get_low_stock_medicines(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin_or_pharmacy(current_doctor)

    medicines = db.query(HospitalMedicine).filter(
        HospitalMedicine.hospital_id == current_doctor.hospital_id,
        HospitalMedicine.is_active == True
    ).all()

    result = []
    for m in medicines:
        stock = m.stock_quantity or 0
        if stock <= m.low_stock_threshold:
            result.append({
                "medicine_id": m.id,
                "medicine_name": f"{m.generic_name}{' ' + m.strength if m.strength else ''}",
                "stock_quantity": stock,
                "low_stock_threshold": m.low_stock_threshold,
                "is_out_of_stock": stock == 0
            })

    result.sort(key=lambda r: r["stock_quantity"])
    return result