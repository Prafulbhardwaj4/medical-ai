import io
import json as _json
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.database import get_db
from app.models.doctor import Doctor
from app.models.import_batch import ImportBatch, ImportPreview
from app.routers.tests import require_admin
from app.services.import_common import ImportFileError, MAX_IMPORT_BYTES, XLSX_MIME, check_xlsx_bytes
from app.services.medicine_import_service import ImportRefused
from app.services.test_import_parser import parse_tests_workbook
from app.services.test_import_service import (
    KIND, PREVIEW_MINUTES, apply_test_plan, plan_test_import, plan_to_dict, save_preview,
    tests_from_preview, undo_test_import,
)
from app.services.test_import_template import build_test_template
from app.utils.auth import get_current_doctor
from app.utils.rate_limit import limiter
from app.utils.timezone import now_ist_naive

# Same roles as the existing test catalog endpoints: admin and sub_admin.
router = APIRouter(prefix="/admin/test-import", tags=["test-import"])
log = logging.getLogger(__name__)


class ConfirmIn(BaseModel):
    preview_id: str


def _hospital_id(d: Doctor) -> int:
    if not d.hospital_id:
        raise HTTPException(status_code=400, detail="Your account is not linked to a hospital.")
    return d.hospital_id


@router.get("/template")
@limiter.limit("30/hour")
def download_test_template(request: Request, current_doctor: Doctor = Depends(get_current_doctor)):
    require_admin(current_doctor)
    return StreamingResponse(
        io.BytesIO(build_test_template()), media_type=XLSX_MIME,
        headers={"Content-Disposition": 'attachment; filename="MedScribe_Tests_Template.xlsx"'})


def _build_preview(db: Session, doctor: Doctor, file_name: str, content: bytes):
    hospital_id = _hospital_id(doctor)
    parsed = parse_tests_workbook(content)
    plan = plan_test_import(db, hospital_id, parsed.tests)
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
        result["preview_id"] = save_preview(db, doctor, hospital_id, file_name, parsed)
    return result


@router.post("/preview")
@limiter.limit("20/hour")
async def preview_test_import(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
                              current_doctor: Doctor = Depends(get_current_doctor)):
    """Reads and checks the file against the hospital's current test catalog. Saves NOTHING to the catalog."""
    require_admin(current_doctor)
    content = await file.read(MAX_IMPORT_BYTES + 1)
    try:
        check_xlsx_bytes(file.filename, content)
        return await run_in_threadpool(_build_preview, db, current_doctor, file.filename, content)
    except ImportFileError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    except HTTPException:
        raise
    except Exception:
        log.exception("Test import preview crashed")
        raise HTTPException(status_code=400, detail="Could not read this file. Make sure it is a valid, unprotected .xlsx made from our template.")


@router.post("/confirm")
@limiter.limit("20/hour")
def confirm_test_import(request: Request, body: ConfirmIn, db: Session = Depends(get_db),
                        current_doctor: Doctor = Depends(get_current_doctor)):
    """ONE transaction, all or nothing. The browser sends only the preview id."""
    require_admin(current_doctor)
    hospital_id = _hospital_id(current_doctor)
    pv = db.query(ImportPreview).filter(ImportPreview.id == body.preview_id).first()
    if pv is None or pv.kind != KIND or pv.doctor_id != current_doctor.id or pv.hospital_id != hospital_id:
        raise HTTPException(status_code=404, detail="Preview not found. Please upload the file again.")
    if pv.consumed:
        raise HTTPException(status_code=400, detail="This preview was already imported. Upload the file again if you need to repeat it.")
    if pv.expires_at < now_ist_naive():
        raise HTTPException(status_code=400, detail="This preview expired. Please upload the file again.")
    plan = plan_test_import(db, hospital_id, tests_from_preview(pv))      # re-checked against the catalog as it is NOW
    if plan.errors:
        raise HTTPException(status_code=409, detail={
            "message": "Your test catalog changed since the preview, so the file no longer fits. Nothing was saved. Upload the file again.",
            "errors": [i.to_dict() for i in plan.errors]})
    if not plan.has_changes():
        raise HTTPException(status_code=400, detail="Nothing to import: everything in this file is already in your test catalog.")
    claimed = db.query(ImportPreview).filter(ImportPreview.id == pv.id, ImportPreview.consumed == False).update(  # noqa: E712
        {"consumed": True}, synchronize_session=False)
    if claimed != 1:
        db.rollback()
        raise HTTPException(status_code=400, detail="This preview was already imported.")
    try:
        batch = apply_test_plan(db, plan, current_doctor, hospital_id, pv.file_name)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Someone changed the catalog at the same moment. Nothing was saved. Please upload the file again.")
    except Exception:
        db.rollback()
        log.exception("Test import apply failed")
        raise HTTPException(status_code=500, detail="Import failed and nothing was saved. Please try again.")
    return {"import_id": batch.id, "summary": _json.loads(batch.summary)}


@router.get("/history")
def test_import_history(db: Session = Depends(get_db), current_doctor: Doctor = Depends(get_current_doctor)):
    require_admin(current_doctor)
    hospital_id = _hospital_id(current_doctor)
    rows = db.query(ImportBatch).filter(ImportBatch.hospital_id == hospital_id, ImportBatch.kind == KIND) \
             .order_by(ImportBatch.id.desc()).limit(10).all()
    latest = next((b.id for b in rows if b.status == "applied"), None)
    return [{"id": b.id, "file_name": b.file_name, "status": b.status,
             "created_at": b.created_at.isoformat() if b.created_at else None, "created_by": b.created_by_name,
             "summary": _json.loads(b.summary or "{}"), "is_latest_applied": b.id == latest and b.status == "applied"}
            for b in rows]


@router.post("/{batch_id}/undo")
@limiter.limit("20/hour")
def undo_test_import_endpoint(request: Request, batch_id: int, db: Session = Depends(get_db),
                              current_doctor: Doctor = Depends(get_current_doctor)):
    require_admin(current_doctor)
    hospital_id = _hospital_id(current_doctor)
    batch = db.query(ImportBatch).filter(ImportBatch.id == batch_id, ImportBatch.hospital_id == hospital_id,
                                         ImportBatch.kind == KIND).first()
    if batch is None:
        raise HTTPException(status_code=404, detail="Import not found.")
    try:
        return undo_test_import(db, batch, current_doctor)
    except ImportRefused as e:
        db.rollback()
        raise HTTPException(status_code=409, detail={"message": e.message, "problems": e.problems})
    except Exception:
        db.rollback()
        log.exception("Test import undo failed")
        raise HTTPException(status_code=500, detail="Undo failed and nothing was changed.")