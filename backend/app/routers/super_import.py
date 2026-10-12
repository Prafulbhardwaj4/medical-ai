"""Super Admin: run the Excel imports (medicines / tests) FOR a chosen hospital.
Same logic as the hospital-side imports (plan -> preview -> confirm -> undo); the only difference is that
the hospital id comes from the URL and only a super_admin may use it. Hospital staff have their own
endpoints (/admin/medicine-import, /admin/test-import) that always use the caller's own hospital."""
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
from app.models.hospital import Hospital
from app.models.import_batch import ImportBatch, ImportPreview
from app.services import medicine_import_service as med_svc
from app.services import test_import_service as test_svc
from app.services.import_common import ImportFileError, MAX_IMPORT_BYTES, XLSX_MIME, check_xlsx_bytes
from app.services.medicine_import_parser import parse_medicines_workbook
from app.services.medicine_import_template import build_medicine_template
from app.services.test_import_parser import parse_tests_workbook
from app.services.test_import_template import build_test_template
from app.utils.audit import log_action
from app.utils.notify import sync_stock_notifications
from app.utils.rate_limit import limiter
from app.utils.roles import require_super_admin
from app.utils.timezone import now_ist_naive

router = APIRouter(prefix="/superadmin/import", tags=["superadmin-import"])
log = logging.getLogger(__name__)
KINDS = ("medicines", "tests")


class ConfirmIn(BaseModel):
    preview_id: str


def _kind(kind: str) -> str:
    if kind not in KINDS:
        raise HTTPException(status_code=404, detail="Unknown import type.")
    return kind


def _hospital(db: Session, hospital_id: int) -> Hospital:
    h = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if h is None:
        raise HTTPException(status_code=404, detail="Hospital not found.")
    return h


def _audit(db, actor, hospital: Hospital, action: str, kind: str, batch_id: int, file_name: str):
    """Extra, explicit trail: a super admin acted on another hospital's data."""
    log_action(db, actor, action=action, target_type="hospital", target_id=hospital.id, target_label=hospital.name,
               details=f"{kind} import #{batch_id} ({file_name or 'file'}) done by super admin for this hospital",
               hospital_id=hospital.id)


@router.get("/template/{kind}")
@limiter.limit("30/hour")
def super_template(request: Request, kind: str, current_doctor: Doctor = Depends(require_super_admin)):
    _kind(kind)
    data = build_medicine_template() if kind == "medicines" else build_test_template()
    name = "MedScribe_Medicines_Template.xlsx" if kind == "medicines" else "MedScribe_Tests_Template.xlsx"
    return StreamingResponse(io.BytesIO(data), media_type=XLSX_MIME,
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _build_preview(db, doctor, hospital_id, kind, file_name, content):
    if kind == "medicines":
        parsed = parse_medicines_workbook(content)
        plan = med_svc.plan_medicine_import(db, hospital_id, doctor.role.value, parsed)
        out = parsed.to_dict(preview_limit=0)
        result = med_svc.plan_to_dict(plan)
        has_changes, svc, expires = plan.has_changes(), med_svc, med_svc.PREVIEW_MINUTES
    else:
        parsed = parse_tests_workbook(content)
        plan = test_svc.plan_test_import(db, hospital_id, parsed.tests)
        out = parsed.to_dict(preview_limit=0)
        result = test_svc.plan_to_dict(plan)
        has_changes, svc, expires = plan.has_changes(), test_svc, test_svc.PREVIEW_MINUTES
    errors = out["errors"] + [i.to_dict() for i in plan.errors]
    warnings = out["warnings"] + [i.to_dict() for i in plan.warnings]
    result.update({"ok": not errors, "errors": errors, "warnings": warnings, "preview_id": None,
                   "expires_in_minutes": expires, "file_name": file_name, "kind": kind})
    result["counts"]["errors"] = len(errors)
    result["counts"]["warnings"] = len(warnings)
    result["nothing_to_change"] = (not errors) and (not has_changes)
    if not errors and has_changes:
        result["preview_id"] = svc.save_preview(db, doctor, hospital_id, file_name, parsed)
    return result


@router.post("/{hospital_id}/{kind}/preview")
@limiter.limit("20/hour")
async def super_preview(request: Request, hospital_id: int, kind: str, file: UploadFile = File(...),
                        db: Session = Depends(get_db), current_doctor: Doctor = Depends(require_super_admin)):
    _kind(kind)
    _hospital(db, hospital_id)
    content = await file.read(MAX_IMPORT_BYTES + 1)
    try:
        check_xlsx_bytes(file.filename, content)
        return await run_in_threadpool(_build_preview, db, current_doctor, hospital_id, kind, file.filename, content)
    except ImportFileError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    except HTTPException:
        raise
    except Exception:
        log.exception("Super admin import preview crashed")
        raise HTTPException(status_code=400, detail="Could not read this file. Make sure it is a valid, unprotected .xlsx made from our template.")


@router.post("/{hospital_id}/{kind}/confirm")
@limiter.limit("20/hour")
def super_confirm(request: Request, hospital_id: int, kind: str, body: ConfirmIn, db: Session = Depends(get_db),
                  current_doctor: Doctor = Depends(require_super_admin)):
    _kind(kind)
    hospital = _hospital(db, hospital_id)
    pv = db.query(ImportPreview).filter(ImportPreview.id == body.preview_id).first()
    if pv is None or pv.kind != kind or pv.doctor_id != current_doctor.id or pv.hospital_id != hospital_id:
        raise HTTPException(status_code=404, detail="Preview not found. Please upload the file again.")
    if pv.consumed:
        raise HTTPException(status_code=400, detail="This preview was already imported. Upload the file again if you need to repeat it.")
    if pv.expires_at < now_ist_naive():
        raise HTTPException(status_code=400, detail="This preview expired. Please upload the file again.")
    role = current_doctor.role.value
    if kind == "medicines":
        plan = med_svc.plan_medicine_import(db, hospital_id, role, med_svc.parse_from_payload(pv.payload))
    else:
        plan = test_svc.plan_test_import(db, hospital_id, test_svc.tests_from_preview(pv))
    if plan.errors:
        raise HTTPException(status_code=409, detail={
            "message": "This hospital's catalog changed since the preview, so the file no longer fits. Nothing was saved. Upload the file again.",
            "errors": [i.to_dict() for i in plan.errors]})
    if not plan.has_changes():
        raise HTTPException(status_code=400, detail="Nothing to import: everything in this file is already in the catalog.")
    claimed = db.query(ImportPreview).filter(ImportPreview.id == pv.id, ImportPreview.consumed == False).update(  # noqa: E712
        {"consumed": True}, synchronize_session=False)
    if claimed != 1:
        db.rollback()
        raise HTTPException(status_code=400, detail="This preview was already imported.")
    try:
        if kind == "medicines":
            batch = med_svc.apply_plan(db, plan, current_doctor, hospital_id, pv.file_name)
        else:
            batch = test_svc.apply_test_plan(db, plan, current_doctor, hospital_id, pv.file_name)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="The catalog changed at the same moment. Nothing was saved. Please upload the file again.")
    except Exception:
        db.rollback()
        log.exception("Super admin import apply failed")
        raise HTTPException(status_code=500, detail="Import failed and nothing was saved. Please try again.")
    try:
        _audit(db, current_doctor, hospital, "super_admin_import_applied", kind, batch.id, pv.file_name)
        if kind == "medicines":
            sync_stock_notifications(db, hospital_id)
    except Exception:
        db.rollback()
        log.exception("post-import audit/notification step failed")
    return {"import_id": batch.id, "summary": _json.loads(batch.summary)}


@router.get("/{hospital_id}/{kind}/history")
def super_history(hospital_id: int, kind: str, db: Session = Depends(get_db),
                  current_doctor: Doctor = Depends(require_super_admin)):
    _kind(kind)
    _hospital(db, hospital_id)
    rows = db.query(ImportBatch).filter(ImportBatch.hospital_id == hospital_id, ImportBatch.kind == kind) \
             .order_by(ImportBatch.id.desc()).limit(10).all()
    latest = next((b.id for b in rows if b.status == "applied"), None)
    return [{"id": b.id, "file_name": b.file_name, "status": b.status,
             "created_at": b.created_at.isoformat() if b.created_at else None,
             "created_by": b.created_by_name, "created_by_role": b.created_by_role,
             "summary": _json.loads(b.summary or "{}"), "is_latest_applied": b.id == latest and b.status == "applied"}
            for b in rows]


@router.post("/{hospital_id}/{kind}/{batch_id}/undo")
@limiter.limit("20/hour")
def super_undo(request: Request, hospital_id: int, kind: str, batch_id: int, db: Session = Depends(get_db),
               current_doctor: Doctor = Depends(require_super_admin)):
    _kind(kind)
    hospital = _hospital(db, hospital_id)
    batch = db.query(ImportBatch).filter(ImportBatch.id == batch_id, ImportBatch.hospital_id == hospital_id,
                                         ImportBatch.kind == kind).first()
    if batch is None:
        raise HTTPException(status_code=404, detail="Import not found.")
    try:
        result = (med_svc.undo_import if kind == "medicines" else test_svc.undo_test_import)(db, batch, current_doctor)
    except med_svc.ImportRefused as e:
        db.rollback()
        raise HTTPException(status_code=409, detail={"message": e.message, "problems": e.problems})
    except Exception:
        db.rollback()
        log.exception("Super admin import undo failed")
        raise HTTPException(status_code=500, detail="Undo failed and nothing was changed.")
    try:
        _audit(db, current_doctor, hospital, "super_admin_import_undone", kind, batch.id, batch.file_name)
        if kind == "medicines":
            sync_stock_notifications(db, hospital_id)
    except Exception:
        db.rollback()
        log.exception("post-undo audit/notification step failed")
    return result