from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional
from pydantic import BaseModel
import io

from app.database import get_db
from app.models.doctor import Doctor
from app.models.test_catalog import TestCatalogItem
from app.models.test_catalog_parameter import TestCatalogParameter
from app.utils.auth import get_current_doctor
from app.utils.audit import log_action
from app.services.groq_service import extract_tests

router = APIRouter(prefix="/admin/tests", tags=["tests"])


def require_admin(current_doctor: Doctor):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")


class ParameterIn(BaseModel):
    name: str
    unit: Optional[str] = ""
    reference_range_male: Optional[str] = ""
    reference_range_female: Optional[str] = ""
    purpose: Optional[str] = ""


class TestIn(BaseModel):
    test_name: str
    category: Optional[str] = ""
    price: Optional[float] = None
    purpose: Optional[str] = ""
    reference_range_male: Optional[str] = ""
    reference_range_female: Optional[str] = ""
    unit: Optional[str] = ""
    turnaround_hours: Optional[int] = None
    is_panel: Optional[bool] = False
    parameters: Optional[list[ParameterIn]] = None


class TestBulkConfirm(BaseModel):
    tests: list[TestIn]


def serialize_parameter(p: TestCatalogParameter):
    return {
        "id": p.id,
        "name": p.name,
        "unit": p.unit or "",
        "reference_range_male": p.reference_range_male or "",
        "reference_range_female": p.reference_range_female or "",
        "purpose": p.purpose or "",
        "display_order": p.display_order
    }


def serialize(t: TestCatalogItem, db: Session = None):
    parameters = []
    if t.is_panel and db is not None:
        rows = db.query(TestCatalogParameter).filter(
            TestCatalogParameter.test_catalog_item_id == t.id,
            TestCatalogParameter.is_active == True
        ).order_by(TestCatalogParameter.display_order).all()
        parameters = [serialize_parameter(p) for p in rows]

    return {
        "id": t.id,
        "test_name": t.name,
        "category": t.category or "",
        "price": t.fee,
        "purpose": t.purpose or "",
        "reference_range_male": t.reference_range_male or "",
        "reference_range_female": t.reference_range_female or "",
        "unit": t.unit or "",
        "turnaround_hours": t.turnaround_hours,
        "is_active": t.is_active,
        "is_panel": t.is_panel,
        "parameters": parameters
    }

@router.get("")
def list_tests(
    category: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin(current_doctor)

    query = db.query(TestCatalogItem).filter(
        TestCatalogItem.hospital_id == current_doctor.hospital_id,
        TestCatalogItem.is_active == True
    )

    if category:
        query = query.filter(TestCatalogItem.category == category)
    if search:
        query = query.filter(TestCatalogItem.name.ilike(f"%{search}%"))

    items = query.order_by(TestCatalogItem.name).all()
    return [serialize(t, db) for t in items]


@router.post("", status_code=201)
def create_test(
    payload: TestIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin(current_doctor)

    if payload.price is None:
        raise HTTPException(status_code=400, detail="Price is required")

    is_panel = bool(payload.is_panel)
    if is_panel and (not payload.parameters or len(payload.parameters) == 0):
        raise HTTPException(status_code=400, detail="A panel needs at least one parameter")

    test = TestCatalogItem(
        hospital_id=current_doctor.hospital_id,
        name=payload.test_name.strip(),
        fee=payload.price,
        category=(payload.category or "").strip(),
        purpose=(payload.purpose or "").strip(),
        is_panel=is_panel,
        # A panel's range/unit live on its parameters, not here — kept blank to avoid confusion.
        reference_range_male="" if is_panel else (payload.reference_range_male or "").strip(),
        reference_range_female="" if is_panel else (payload.reference_range_female or "").strip(),
        unit="" if is_panel else (payload.unit or "").strip(),
        turnaround_hours=payload.turnaround_hours,
        is_active=True
    )
    db.add(test)
    db.commit()
    db.refresh(test)

    if is_panel:
        for i, p in enumerate(payload.parameters):
            if not p.name or not p.name.strip():
                continue
            db.add(TestCatalogParameter(
                test_catalog_item_id=test.id,
                hospital_id=current_doctor.hospital_id,
                name=p.name.strip(),
                unit=(p.unit or "").strip(),
                reference_range_male=(p.reference_range_male or "").strip(),
                reference_range_female=(p.reference_range_female or "").strip(),
                purpose=(p.purpose or "").strip(),
                display_order=i,
                is_active=True
            ))
        db.commit()

    log_action(
        db, current_doctor,
        action="test_created",
        target_type="test_catalog_item",
        target_id=test.id,
        target_label=test.name,
        hospital_id=current_doctor.hospital_id
    )
    return serialize(test, db)


@router.patch("/{test_id}")
def update_test(
    test_id: int,
    payload: TestIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin(current_doctor)

    test = db.query(TestCatalogItem).filter(
        TestCatalogItem.id == test_id,
        TestCatalogItem.hospital_id == current_doctor.hospital_id
    ).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")

    if payload.price is None:
        raise HTTPException(status_code=400, detail="Price is required")

    is_panel = bool(payload.is_panel)
    if is_panel and (not payload.parameters or len(payload.parameters) == 0):
        raise HTTPException(status_code=400, detail="A panel needs at least one parameter")

    test.name = payload.test_name.strip()
    test.fee = payload.price
    test.category = (payload.category or "").strip()
    test.purpose = (payload.purpose or "").strip()
    test.is_panel = is_panel
    test.reference_range_male = "" if is_panel else (payload.reference_range_male or "").strip()
    test.reference_range_female = "" if is_panel else (payload.reference_range_female or "").strip()
    test.unit = "" if is_panel else (payload.unit or "").strip()
    test.turnaround_hours = payload.turnaround_hours

    # Replace-all: simplest and safest way to sync a small, admin-managed parameter
    # list without diffing rows. Existing parameter rows for this test are wiped
    # and rebuilt from the payload every save.
    db.query(TestCatalogParameter).filter(
        TestCatalogParameter.test_catalog_item_id == test.id
    ).delete()

    if is_panel:
        for i, p in enumerate(payload.parameters):
            if not p.name or not p.name.strip():
                continue
            db.add(TestCatalogParameter(
                test_catalog_item_id=test.id,
                hospital_id=current_doctor.hospital_id,
                name=p.name.strip(),
                unit=(p.unit or "").strip(),
                reference_range_male=(p.reference_range_male or "").strip(),
                reference_range_female=(p.reference_range_female or "").strip(),
                purpose=(p.purpose or "").strip(),
                display_order=i,
                is_active=True
            ))

    db.commit()

    log_action(
        db, current_doctor,
        action="test_updated",
        target_type="test_catalog_item",
        target_id=test.id,
        target_label=test.name,
        hospital_id=current_doctor.hospital_id
    )
    return serialize(test, db)


@router.delete("/{test_id}")
def deactivate_test(
    test_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin(current_doctor)

    test = db.query(TestCatalogItem).filter(
        TestCatalogItem.id == test_id,
        TestCatalogItem.hospital_id == current_doctor.hospital_id
    ).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")

    test.is_active = False
    db.commit()

    log_action(
        db, current_doctor,
        action="test_deactivated",
        target_type="test_catalog_item",
        target_id=test.id,
        target_label=test.name,
        hospital_id=current_doctor.hospital_id
    )
    return {"id": test.id, "is_active": test.is_active}


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
async def upload_tests(
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
        extracted = await extract_tests(raw_text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Extraction failed: {str(e)}")

    return {"tests": extracted}


@router.post("/bulk-confirm")
def bulk_confirm_tests(
    payload: TestBulkConfirm,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_admin(current_doctor)

    created = []
    for item in payload.tests:
        if not item.test_name or not item.test_name.strip():
            continue

        is_panel = bool(item.is_panel)

        test = TestCatalogItem(
            hospital_id=current_doctor.hospital_id,
            name=item.test_name.strip(),
            fee=item.price if item.price is not None else 0,
            category=(item.category or "").strip(),
            purpose=(item.purpose or "").strip(),
            is_panel=is_panel,
            reference_range_male="" if is_panel else (item.reference_range_male or "").strip(),
            reference_range_female="" if is_panel else (item.reference_range_female or "").strip(),
            unit="" if is_panel else (item.unit or "").strip(),
            turnaround_hours=item.turnaround_hours,
            is_active=True
        )
        db.add(test)
        db.flush()

        if is_panel and item.parameters:
            for i, p in enumerate(item.parameters):
                if not p.name or not p.name.strip():
                    continue
                db.add(TestCatalogParameter(
                    test_catalog_item_id=test.id,
                    hospital_id=current_doctor.hospital_id,
                    name=p.name.strip(),
                    unit=(p.unit or "").strip(),
                    reference_range_male=(p.reference_range_male or "").strip(),
                    reference_range_female=(p.reference_range_female or "").strip(),
                    purpose=(p.purpose or "").strip(),
                    display_order=i,
                    is_active=True
                ))

        created.append(test)

    db.commit()
    for t in created:
        db.refresh(t)

    log_action(
        db, current_doctor,
        action="tests_bulk_imported",
        target_type="test_catalog_item",
        target_id=0,
        target_label=f"{len(created)} tests",
        hospital_id=current_doctor.hospital_id
    )
    return [serialize(t, db) for t in created]