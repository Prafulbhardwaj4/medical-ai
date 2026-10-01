from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from sqlalchemy.exc import IntegrityError
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
from app.utils.inventory import expired_units_by_medicine

router = APIRouter(prefix="/admin/medicines", tags=["medicines"])

VALID_SCHEDULES = {"otc", "h", "h1", "x"}
NEAR_EXPIRY_DAYS = 30  # named constant so the near-expiry cutoff is easy to adjust laterVALID_SCHEDULES = {"otc", "h", "h1", "x"}


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
    hsn_code: Optional[str] = None
    nppa_ceiling_price: Optional[float] = None


VALID_BILLING_MODES = {"per_unit", "per_pack"}

MAX_PRICE = 1_000_000      # Rs per pack / NPPA ceiling
MAX_GST_PERCENT = 28       # highest Indian GST slab
MAX_PACK_SIZE = 10_000
MAX_THRESHOLD = 1_000_000


def _number_problem(price_per_pack=None, gst_percent=None, nppa_ceiling_price=None, low_stock_threshold=None, pack_size=None):
    """Returns a human-readable problem string, or None when every number is sane."""
    if price_per_pack is not None and not (0 <= price_per_pack <= MAX_PRICE):
        return f"Price per pack must be between 0 and {MAX_PRICE:,}"
    if gst_percent is not None and not (0 <= gst_percent <= MAX_GST_PERCENT):
        return f"GST % must be between 0 and {MAX_GST_PERCENT}"
    if nppa_ceiling_price is not None and not (0 <= nppa_ceiling_price <= MAX_PRICE):
        return f"NPPA ceiling price must be between 0 and {MAX_PRICE:,}"
    if low_stock_threshold is not None and not (0 <= low_stock_threshold <= MAX_THRESHOLD):
        return f"Low-stock threshold must be between 0 and {MAX_THRESHOLD:,}"
    if pack_size is not None and not (1 <= pack_size <= MAX_PACK_SIZE):
        return f"Pack size must be between 1 and {MAX_PACK_SIZE:,}"
    return None


def _find_duplicate_medicine(db, hospital_id, generic_name, strength, dosage_forms):
    """Active generic (non-brand) row with the same generic name + strength + form."""
    return db.query(HospitalMedicine).filter(
        HospitalMedicine.hospital_id == hospital_id,
        HospitalMedicine.parent_medicine_id == None,  # noqa: E711
        HospitalMedicine.is_active == True,
        func.lower(func.trim(HospitalMedicine.generic_name)) == (generic_name or "").strip().lower(),
        func.lower(func.trim(func.coalesce(HospitalMedicine.strength, ""))) == (strength or "").strip().lower(),
        func.lower(func.trim(func.coalesce(HospitalMedicine.dosage_forms, ""))) == (dosage_forms or "").strip().lower(),
    ).first()


def compute_unit_price(price_per_pack, pack_size):
    if price_per_pack is None or not pack_size or pack_size < 1:
        return None
    # Deliberately NOT rounded: rounding here made a Rs100 strip of 15 bill Rs100.05.
    # Line totals are rounded once, in utils.inventory.line_total.
    return price_per_pack / pack_size


class MedicineBulkConfirm(BaseModel):
    medicines: list[MedicineIn]


class BrandIn(BaseModel):
    brand_name: str
    price_per_pack: Optional[float] = None
    low_stock_threshold: Optional[int] = None
    strength: Optional[str] = None  # overrides the parent's strength for this brand only; falls back to parent's if not given


def serialize(m: HospitalMedicine, expired_units: int = 0):
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
        "hsn_code": m.hsn_code,
        "price": round(m.price, 2) if m.price is not None else None,  # display only - billing uses the unrounded value
        "nppa_ceiling_price": m.nppa_ceiling_price,
        "stock_quantity": m.stock_quantity,
        "expired_quantity": expired_units,  # units sitting in expired batches - not sellable
        "sellable_quantity": max(0, (m.stock_quantity or 0) - expired_units) if m.stock_quantity is not None else None,
        "is_active": m.is_active
    }


def _ceiling_price_warning(medicine: HospitalMedicine):
    """DPCO ceiling check — this is admin-entered reference data with no live
    NPPA feed, so it's a warning, not a hard block: a stale locally-stored
    ceiling shouldn't be able to trap admin from correcting a price. Compared
    against the computed per-unit price, since NPPA ceilings are quoted
    per-tablet/unit, not per-pack (packs vary in size across brands)."""
    if medicine.nppa_ceiling_price is None or medicine.price is None:
        return None
    if medicine.price > medicine.nppa_ceiling_price:
        return (
            f"Price ₹{medicine.price:.2f}/unit exceeds the stored NPPA/DPCO ceiling of "
            f"₹{medicine.nppa_ceiling_price:.2f}/unit for {medicine.generic_name}. Double-check before saving."
        )
    return None


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
    expired_map = expired_units_by_medicine(db, hospital_id=current_doctor.hospital_id)
    return [serialize(m, expired_map.get(m.id, 0)) for m in items]


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
    problem = _number_problem(payload.price_per_pack, payload.gst_percent, payload.nppa_ceiling_price, payload.low_stock_threshold, pack_size)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    if not (payload.generic_name or "").strip():
        raise HTTPException(status_code=400, detail="Generic name is required")
    if _find_duplicate_medicine(db, current_doctor.hospital_id, payload.generic_name, payload.strength, payload.dosage_forms):
        raise HTTPException(status_code=400, detail="This medicine (same name, strength and form) is already in your catalog. Edit the existing one or add a brand to it.")

    medicine = HospitalMedicine(
        hospital_id=current_doctor.hospital_id,
        generic_name=payload.generic_name.strip(),
        brand_names=(payload.brand_names or "").strip(),
        category=(payload.category or "").strip(),
        dosage_forms=(payload.dosage_forms or "").strip(),
        strength=(payload.strength or "").strip(),
        schedule=schedule,
        low_stock_threshold=payload.low_stock_threshold if payload.low_stock_threshold is not None else 25,
        pack_size=pack_size,
        price_per_pack=payload.price_per_pack,
        nppa_ceiling_price=payload.nppa_ceiling_price,
        billing_mode=billing_mode,
        gst_percent=payload.gst_percent,
        hsn_code=(payload.hsn_code or "").strip() or None,
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
    result = serialize(medicine)
    warning = _ceiling_price_warning(medicine)
    if warning:
        result["warning"] = warning
    return result


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
    problem = _number_problem(price_per_pack=payload.price_per_pack, low_stock_threshold=payload.low_stock_threshold)
    if problem:
        raise HTTPException(status_code=400, detail=problem)

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
        strength=(payload.strength.strip() if payload.strength else root.strength),
        schedule=root.schedule,
        brand_name=brand_name,
        parent_medicine_id=root.id,
        low_stock_threshold=(payload.low_stock_threshold if payload.low_stock_threshold is not None
                             else (root.low_stock_threshold if root.low_stock_threshold is not None else 25)),
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
    require_admin_or_pharmacy(current_doctor)

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
    problem = _number_problem(payload.price_per_pack, payload.gst_percent, payload.nppa_ceiling_price, payload.low_stock_threshold, pack_size)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    if not (payload.generic_name or "").strip():
        raise HTTPException(status_code=400, detail="Generic name is required")

    _audited_fields = ["generic_name", "brand_names", "category", "dosage_forms", "strength", "schedule",
                       "low_stock_threshold", "pack_size", "price_per_pack", "billing_mode", "gst_percent",
                       "hsn_code", "nppa_ceiling_price"]
    _before = {f: getattr(medicine, f) for f in _audited_fields}

    medicine.generic_name = payload.generic_name.strip()
    medicine.brand_names = (payload.brand_names or "").strip()
    medicine.category = (payload.category or "").strip()
    medicine.dosage_forms = (payload.dosage_forms or "").strip()
    medicine.strength = (payload.strength or "").strip()
    medicine.schedule = schedule
    medicine.low_stock_threshold = payload.low_stock_threshold if payload.low_stock_threshold is not None else 25
    medicine.pack_size = pack_size
    medicine.price_per_pack = payload.price_per_pack
    medicine.billing_mode = billing_mode
    medicine.gst_percent = payload.gst_percent
    medicine.hsn_code = (payload.hsn_code or "").strip() or None
    medicine.price = compute_unit_price(payload.price_per_pack, pack_size)
    medicine.nppa_ceiling_price = payload.nppa_ceiling_price
    # stock_quantity is deliberately NOT touched here — it's owned exclusively
    # by the batch endpoints (add/edit/delete batch). Editing catalog details
    # must never affect live stock.
    db.commit()

    _changes = [f"{f}: {_before[f]!r} -> {getattr(medicine, f)!r}" for f in _audited_fields if _before[f] != getattr(medicine, f)]
    log_action(
        db, current_doctor,
        action="medicine_updated",
        target_type="hospital_medicine",
        target_id=medicine.id,
        target_label=medicine.generic_name,
        details="; ".join(_changes) if _changes else "no field changed",
        hospital_id=current_doctor.hospital_id
    )
    result = serialize(medicine)
    warning = _ceiling_price_warning(medicine)
    if warning:
        result["warning"] = warning
    return result


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


MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


@router.post("/upload")
async def upload_medicines(
    file: UploadFile = File(...),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin_or_pharmacy(current_doctor)

    filename = (file.filename or "").lower()
    if filename.endswith(".xls"):
        raise HTTPException(status_code=400, detail="Old .xls files are not supported. Open it in Excel, choose Save As .xlsx, and upload that.")
    if not (filename.endswith(".pdf") or filename.endswith(".xlsx")):
        raise HTTPException(status_code=400, detail="Only PDF or .xlsx Excel files are supported")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is too large (maximum 10 MB). Split it into smaller files.")

    try:
        if filename.endswith(".pdf"):
            raw_text = _extract_text_from_pdf(content)
        else:
            raw_text = _extract_text_from_excel(content)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read this file. Make sure it is a valid, unprotected PDF or .xlsx.")

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
    skipped = []
    seen_keys = set()
    for item in payload.medicines:
        name = (item.generic_name or "").strip()
        if not name or len(name) > 200:
            skipped.append({"name": name[:60] or "(blank)", "reason": "Missing or invalid name"})
            continue
        problem = _number_problem(item.price_per_pack, item.gst_percent, item.nppa_ceiling_price, item.low_stock_threshold, item.pack_size or 1)
        if problem:
            skipped.append({"name": name, "reason": problem})
            continue
        key = (name.lower(), (item.strength or "").strip().lower(), (item.dosage_forms or "").strip().lower())
        if key in seen_keys or _find_duplicate_medicine(db, current_doctor.hospital_id, name, item.strength, item.dosage_forms):
            skipped.append({"name": name, "reason": "Already in your catalog"})
            continue
        seen_keys.add(key)

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
            generic_name=name,
            brand_names=(item.brand_names or "").strip(),
            category=(item.category or "").strip(),
            dosage_forms=(item.dosage_forms or "").strip(),
            strength=(item.strength or "").strip(),
            schedule=schedule,
            pack_size=pack_size,
            price_per_pack=item.price_per_pack,
            nppa_ceiling_price=item.nppa_ceiling_price,
            low_stock_threshold=item.low_stock_threshold if item.low_stock_threshold is not None else 25,
            billing_mode=billing_mode,
            gst_percent=item.gst_percent,
            hsn_code=(item.hsn_code or "").strip() or None,
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
    return {"created": [serialize(m) for m in created], "skipped": skipped}

class BatchIn(BaseModel):
    quantity: int
    expiry_date: Optional[date] = None
    batch_number: Optional[str] = ""
    reason: Optional[str] = None   # required by edit_batch when the quantity goes DOWN (see WRITE_OFF_REASONS)
    note: Optional[str] = None


WRITE_OFF_REASONS = {"expired", "damaged", "theft_loss", "correction", "returned_to_supplier", "other"}


class WriteOffIn(BaseModel):
    reason: str
    note: Optional[str] = None


def _batch_snapshot(b: MedicineBatch) -> str:
    return f"lot={b.batch_number or '-'}, qty={b.quantity}, expiry={b.expiry_date.isoformat() if b.expiry_date else '-'}"


def _clean_reason(reason, note):
    reason = (reason or "").strip().lower()
    if reason not in WRITE_OFF_REASONS:
        raise HTTPException(status_code=400, detail="Choose a reason: " + ", ".join(sorted(WRITE_OFF_REASONS)))
    note = (note or "").strip()[:200]
    if reason == "other" and not note:
        raise HTTPException(status_code=400, detail="Please add a short note for reason 'other'")
    return reason, note


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
    batch = None
    if batch_number:
        # The DB enforces one row per (medicine, lot number) - including sold-out
        # rows - so the app check must look at ALL rows too (it used to ignore
        # quantity-0 rows, which crashed with a 500 on re-adding a sold-out lot).
        existing = db.query(MedicineBatch).filter(
            MedicineBatch.medicine_id == medicine_id,
            MedicineBatch.batch_number == batch_number,
        ).first()
        if existing and existing.quantity > 0:
            raise HTTPException(status_code=400, detail=f"Batch/Lot '{batch_number}' already exists for this medicine. Edit the existing batch instead, or use a different lot number.")
        if existing:
            # Sold-out lot received again: revive the same row (keeps the lot's
            # history and traceability in one place) instead of creating a twin.
            existing.quantity = payload.quantity
            existing.expiry_date = payload.expiry_date
            existing.received_date = ist_today()
            batch = existing

    if batch is None:
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
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Batch/Lot '{batch_number}' already exists for this medicine. Please refresh and edit the existing batch.")
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
        ).first()
        if duplicate:
            raise HTTPException(status_code=400, detail=f"Batch/Lot '{batch_number}' already exists for this medicine" + (" (sold out - add stock to that lot instead)." if duplicate.quantity <= 0 else "."))

    # Reducing stock by hand is a stock loss/correction - it must say why.
    reason = note = ""
    if payload.quantity < batch.quantity:
        reason, note = _clean_reason(payload.reason, payload.note)

    medicine = db.query(HospitalMedicine).filter(HospitalMedicine.id == batch.medicine_id).first()
    before = _batch_snapshot(batch)
    if medicine:
        # keep the aggregate stock in sync with the quantity change on this batch
        medicine.stock_quantity = max(0, (medicine.stock_quantity or 0) - batch.quantity + payload.quantity)

    batch.quantity = payload.quantity
    batch.expiry_date = payload.expiry_date
    batch.batch_number = batch_number or None
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Batch/Lot '{batch_number}' already exists for this medicine.")
    db.refresh(batch)
    sync_stock_notifications(db, current_doctor.hospital_id)

    log_action(
        db, current_doctor,
        action="medicine_batch_edited",
        target_type="medicine_batch",
        target_id=batch.id,
        target_label=medicine.generic_name if medicine else None,
        details=f"before: {before} | after: {_batch_snapshot(batch)}" + (f" | reason={reason}" + (f" ({note})" if note else "") if reason else ""),
        hospital_id=current_doctor.hospital_id
    )
    return serialize_batch(batch)


@router.post("/batches/{batch_id}/write-off")
def write_off_batch(
    batch_id: int,
    payload: WriteOffIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Write the remaining units of a batch off to zero (expired, damaged, theft/loss,
    correction, returned to supplier). The batch row is KEPT with quantity 0, so its
    lot/expiry history stays; the audit log records who, how many units, and why."""
    require_admin_or_pharmacy(current_doctor)
    reason, note = _clean_reason(payload.reason, payload.note)

    batch = db.query(MedicineBatch).filter(
        MedicineBatch.id == batch_id,
        MedicineBatch.hospital_id == current_doctor.hospital_id
    ).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.quantity <= 0:
        raise HTTPException(status_code=400, detail="This batch is already at zero")

    medicine = db.query(HospitalMedicine).filter(HospitalMedicine.id == batch.medicine_id).first()
    written_off = batch.quantity
    before = _batch_snapshot(batch)
    if medicine:
        medicine.stock_quantity = max(0, (medicine.stock_quantity or 0) - written_off)
    batch.quantity = 0
    db.commit()
    sync_stock_notifications(db, current_doctor.hospital_id)

    log_action(
        db, current_doctor,
        action="medicine_batch_written_off",
        target_type="medicine_batch",
        target_id=batch.id,
        target_label=f"{medicine.generic_name if medicine else 'medicine'} -{written_off}",
        details=f"before: {before} | after: qty=0 | written_off={written_off} | reason={reason}" + (f" ({note})" if note else ""),
        hospital_id=current_doctor.hospital_id
    )
    return {"written_off": written_off, "batch": serialize_batch(batch)}


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

    # A batch that still holds stock can't just vanish - that erased the only record of
    # the loss. Write it off first (with a reason); only empty rows can be removed.
    if batch.quantity > 0:
        raise HTTPException(status_code=400, detail=f"This batch still has {batch.quantity} units. Write it off first (choose a reason) - it can be removed once it is at zero.")

    medicine = db.query(HospitalMedicine).filter(HospitalMedicine.id == batch.medicine_id).first()
    snapshot = _batch_snapshot(batch)
    batch_pk = batch.id
    db.delete(batch)
    db.commit()
    sync_stock_notifications(db, current_doctor.hospital_id)

    log_action(
        db, current_doctor,
        action="medicine_batch_removed",
        target_type="medicine_batch",
        target_id=batch_pk,
        target_label=medicine.generic_name if medicine else None,
        details=f"removed empty batch: {snapshot}",
        hospital_id=current_doctor.hospital_id
    )
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
            "is_expired": days_left < 0,
            "is_near_expiry": 0 <= days_left <= NEAR_EXPIRY_DAYS,
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
    expired_map = expired_units_by_medicine(db, hospital_id=current_doctor.hospital_id)
    for m in medicines:
        stock = max(0, (m.stock_quantity or 0) - expired_map.get(m.id, 0))  # expired units don't count
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