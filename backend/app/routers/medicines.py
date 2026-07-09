from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional
from pydantic import BaseModel
import io

from app.database import get_db
from app.models.doctor import Doctor
from app.models.hospital_medicine import HospitalMedicine
from app.utils.auth import get_current_doctor
from app.utils.audit import log_action
from app.services.groq_service import extract_medicines

router = APIRouter(prefix="/admin/medicines", tags=["medicines"])

VALID_SCHEDULES = {"otc", "h", "h1", "x"}


def require_admin(current_doctor: Doctor):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")


class MedicineIn(BaseModel):
    generic_name: str
    brand_names: Optional[str] = ""
    category: Optional[str] = ""
    dosage_forms: Optional[str] = ""
    strength: Optional[str] = ""
    schedule: Optional[str] = "otc"
    pack_size: Optional[int] = 1
    price_per_pack: Optional[float] = None
    billing_mode: Optional[str] = "per_unit"
    gst_percent: Optional[float] = None
    stock_quantity: Optional[int] = None


VALID_BILLING_MODES = {"per_unit", "per_pack"}


def compute_unit_price(price_per_pack, pack_size):
    if price_per_pack is None or not pack_size or pack_size < 1:
        return None
    return round(price_per_pack / pack_size, 2)


class MedicineBulkConfirm(BaseModel):
    medicines: list[MedicineIn]


def serialize(m: HospitalMedicine):
    return {
        "id": m.id,
        "generic_name": m.generic_name,
        "brand_names": m.brand_names or "",
        "category": m.category or "",
        "dosage_forms": m.dosage_forms or "",
        "strength": m.strength or "",
        "schedule": m.schedule,
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
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin(current_doctor)

    query = db.query(HospitalMedicine).filter(
        HospitalMedicine.hospital_id == current_doctor.hospital_id,
        HospitalMedicine.is_active == True
    )

    if category:
        query = query.filter(HospitalMedicine.category == category)
    if schedule:
        query = query.filter(HospitalMedicine.schedule == schedule)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(
            HospitalMedicine.generic_name.ilike(like),
            HospitalMedicine.brand_names.ilike(like)
        ))

    items = query.order_by(HospitalMedicine.generic_name).all()
    return [serialize(m) for m in items]


@router.post("", status_code=201)
def create_medicine(
    payload: MedicineIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin(current_doctor)

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
        pack_size=pack_size,
        price_per_pack=payload.price_per_pack,
        billing_mode=billing_mode,
        gst_percent=payload.gst_percent,
        price=compute_unit_price(payload.price_per_pack, pack_size),
        stock_quantity=payload.stock_quantity,
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
    medicine.pack_size = pack_size
    medicine.price_per_pack = payload.price_per_pack
    medicine.billing_mode = billing_mode
    medicine.gst_percent = payload.gst_percent
    medicine.price = compute_unit_price(payload.price_per_pack, pack_size)
    medicine.stock_quantity = payload.stock_quantity
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
    require_admin(current_doctor)

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
    require_admin(current_doctor)

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
            stock_quantity=item.stock_quantity,
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