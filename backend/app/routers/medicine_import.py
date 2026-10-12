import io
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.models.doctor import Doctor
from app.routers.medicines import require_admin_or_pharmacy
from app.services.import_common import ImportFileError, MAX_IMPORT_BYTES, XLSX_MIME, check_xlsx_bytes
from app.services.medicine_import_parser import parse_medicines_workbook
from app.services.medicine_import_template import build_medicine_template
from app.utils.auth import get_current_doctor
from app.utils.rate_limit import limiter

router = APIRouter(prefix="/admin/medicine-import", tags=["medicine-import"])
log = logging.getLogger(__name__)


@router.get("/template")
@limiter.limit("30/hour")
def download_medicine_template(request: Request, current_doctor: Doctor = Depends(get_current_doctor)):
    require_admin_or_pharmacy(current_doctor)
    data = build_medicine_template()
    return StreamingResponse(
        io.BytesIO(data), media_type=XLSX_MIME,
        headers={"Content-Disposition": 'attachment; filename="MedScribe_Medicines_Template.xlsx"'},
    )


@router.post("/validate")
@limiter.limit("20/hour")
async def validate_medicine_file(
    request: Request,
    file: UploadFile = File(...),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    """PHASE 1 DRY RUN: reads and checks the file, returns every problem. Saves NOTHING.
    (Phase 2 replaces this with the real preview.)"""
    require_admin_or_pharmacy(current_doctor)
    content = await file.read(MAX_IMPORT_BYTES + 1)
    try:
        check_xlsx_bytes(file.filename, content)
        result = await run_in_threadpool(parse_medicines_workbook, content)
    except ImportFileError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    except Exception:
        log.exception("Medicine import validation crashed")
        raise HTTPException(status_code=400, detail="Could not read this file. Make sure it is a valid, unprotected .xlsx made from our template.")
    return result.to_dict()


# ======================= PHASE 2: preview, confirm, history, undo =======================
import json as _json
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.import_batch import ImportBatch, ImportPreview
from app.services.medicine_import_service import (
    ImportRefused, KIND, apply_plan, parse_from_payload, plan_medicine_import, plan_to_dict,
    save_preview, undo_import, PREVIEW_MINUTES,
)
from app.utils.notify import sync_stock_notifications
from app.utils.timezone import now_ist_naive


class ConfirmIn(BaseModel):
    preview_id: str


def _hospital_id(current_doctor: Doctor) -> int:
    if not current_doctor.hospital_id:
        raise HTTPException(status_code=400, detail="Your account is not linked to a hospital.")
    return current_doctor.hospital_id


def _build_preview(db: Session, current_doctor: Doctor, file_name: str, content: bytes):
    hospital_id = _hospital_id(current_doctor)
    parsed = parse_medicines_workbook(content)
    plan = plan_medicine_import(db, hospital_id, current_doctor.role.value, parsed)
    out = parsed.to_dict(preview_limit=0)
    errors = out["errors"] + [i.to_dict() for i in plan.errors]
    warnings = out["warnings"] + [i.to_dict() for i in plan.warnings]
    result = plan_to_dict(plan)
    result.update({"ok": not errors, "errors": errors, "warnings": warnings, "preview_id": None,
                   "expires_in_minutes": PREVIEW_MINUTES, "file_name": file_name})
    result["counts"]["errors"] = len(errors)
    result["counts"]["warnings"] = len(warnings)
    result["nothing_to_change"] = (not errors) and (not plan.has_changes())
    if not errors and plan.has_changes():
        result["preview_id"] = save_preview(db, current_doctor, hospital_id, file_name, parsed)
    return result


@router.post("/preview")
@limiter.limit("20/hour")
async def preview_medicine_import(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    """Reads and checks the file against the hospital's current catalog. Saves NOTHING to the catalog."""
    require_admin_or_pharmacy(current_doctor)
    content = await file.read(MAX_IMPORT_BYTES + 1)
    try:
        check_xlsx_bytes(file.filename, content)
        return await run_in_threadpool(_build_preview, db, current_doctor, file.filename, content)
    except ImportFileError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    except HTTPException:
        raise
    except Exception:
        log.exception("Medicine import preview crashed")
        raise HTTPException(status_code=400, detail="Could not read this file. Make sure it is a valid, unprotected .xlsx made from our template.")


@router.post("/confirm")
@limiter.limit("20/hour")
def confirm_medicine_import(
    request: Request,
    body: ConfirmIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    """Saves the previewed file: ONE transaction, all or nothing. The browser sends only the preview id."""
    require_admin_or_pharmacy(current_doctor)
    hospital_id = _hospital_id(current_doctor)
    pv = db.query(ImportPreview).filter(ImportPreview.id == body.preview_id).first()
    if (pv is None or pv.kind != KIND or pv.doctor_id != current_doctor.id or pv.hospital_id != hospital_id):
        raise HTTPException(status_code=404, detail="Preview not found. Please upload the file again.")
    if pv.consumed:
        raise HTTPException(status_code=400, detail="This preview was already imported. Upload the file again if you need to repeat it.")
    if pv.expires_at < now_ist_naive():
        raise HTTPException(status_code=400, detail="This preview expired. Please upload the file again.")

    parsed = parse_from_payload(pv.payload)
    plan = plan_medicine_import(db, hospital_id, current_doctor.role.value, parsed)   # re-checked against the catalog as it is NOW
    if plan.errors:
        raise HTTPException(status_code=409, detail={
            "message": "Your catalog changed since the preview, so the file no longer fits. Nothing was saved. Upload the file again.",
            "errors": [i.to_dict() for i in plan.errors]})
    if not plan.has_changes():
        raise HTTPException(status_code=400, detail="Nothing to import: everything in this file is already in your catalog.")
    claimed = db.query(ImportPreview).filter(ImportPreview.id == pv.id, ImportPreview.consumed == False).update(  # noqa: E712
        {"consumed": True}, synchronize_session=False)
    if claimed != 1:
        db.rollback()
        raise HTTPException(status_code=400, detail="This preview was already imported.")
    try:
        batch = apply_plan(db, plan, current_doctor, hospital_id, pv.file_name)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Someone changed the catalog at the same moment. Nothing was saved. Please upload the file again.")
    except Exception:
        db.rollback()
        log.exception("Medicine import apply failed")
        raise HTTPException(status_code=500, detail="Import failed and nothing was saved. Please try again.")
    try:
        sync_stock_notifications(db, hospital_id)
    except Exception:
        db.rollback()
        log.exception("sync_stock_notifications failed after import")
    return {"import_id": batch.id, "summary": _json.loads(batch.summary)}


def _batch_row(b: ImportBatch, latest_id):
    return {"id": b.id, "file_name": b.file_name, "status": b.status,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "created_by": b.created_by_name, "summary": _json.loads(b.summary or "{}"),
            "is_latest_applied": b.id == latest_id and b.status == "applied"}


@router.get("/history")
def medicine_import_history(db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    require_admin_or_pharmacy(current_doctor)
    hospital_id = _hospital_id(current_doctor)
    rows = db.query(ImportBatch).filter(ImportBatch.hospital_id == hospital_id, ImportBatch.kind == KIND) \
             .order_by(ImportBatch.id.desc()).limit(10).all()
    latest = next((b.id for b in rows if b.status == "applied"), None)
    return [_batch_row(b, latest) for b in rows]


@router.post("/{batch_id}/undo")
@limiter.limit("20/hour")
def undo_medicine_import(
    request: Request,
    batch_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor),
):
    require_admin_or_pharmacy(current_doctor)
    hospital_id = _hospital_id(current_doctor)
    batch = db.query(ImportBatch).filter(ImportBatch.id == batch_id, ImportBatch.hospital_id == hospital_id,
                                         ImportBatch.kind == KIND).first()
    if batch is None:
        raise HTTPException(status_code=404, detail="Import not found.")
    try:
        result = undo_import(db, batch, current_doctor)
    except ImportRefused as e:
        db.rollback()
        raise HTTPException(status_code=409, detail={"message": e.message, "problems": e.problems})
    except Exception:
        db.rollback()
        log.exception("Medicine import undo failed")
        raise HTTPException(status_code=500, detail="Undo failed and nothing was changed.")
    try:
        sync_stock_notifications(db, hospital_id)
    except Exception:
        db.rollback()
        log.exception("sync_stock_notifications failed after undo")
    return result