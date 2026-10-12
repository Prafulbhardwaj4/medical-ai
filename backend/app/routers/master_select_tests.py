"""Hospital: choose tests from the MASTER list, set the price, done (ticks or a two-column Excel file).
admin and sub_admin for their own hospital; super_admin on behalf of a hospital (passes hospital_id).
Not tier-gated. Pharmacy/lab/ordering flows are not touched: the hospital just gets normal test rows."""
import io
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.database import get_db
from app.models.doctor import Doctor
from app.models.import_batch import ImportBatch
from app.services import master_select_tests_service as svc
from app.services.import_common import ImportFileError, MAX_IMPORT_BYTES, XLSX_MIME, check_xlsx_bytes
from app.services.medicine_import_service import ImportRefused
from app.utils.master_scope import resolve_hospital
from app.utils.rate_limit import limiter
from app.utils.roles import require_roles

router = APIRouter(prefix="/admin/master-select/tests", tags=["master-select-tests"])
log = logging.getLogger(__name__)

# admin and sub_admin (same as the test catalog), plus super_admin on behalf of a hospital.
_roles = require_roles("admin", "sub_admin", "super_admin")


class SelectedTest(BaseModel):
    master_test_id: int
    price: Optional[float] = None


class AddIn(BaseModel):
    items: list[SelectedTest]


class ConfirmIn(BaseModel):
    preview_id: str


class AcceptIn(BaseModel):
    row: int
    master_test_id: int


@router.get("/list")
def list_master_for_hospital(hospital_id: Optional[int] = None, search: Optional[str] = None,
                             category: Optional[str] = None, db: Session = Depends(get_db),
                             current_doctor: Doctor = Depends(_roles)):
    hospital = resolve_hospital(db, current_doctor, hospital_id)
    out = svc.list_for_hospital(db, hospital.id, search, category)
    out["hospital"] = {"id": hospital.id, "name": hospital.name}
    return out


@router.post("/add")
@limiter.limit("60/hour")
def add_selected_tests(request: Request, body: AddIn, hospital_id: Optional[int] = None,
                       db: Session = Depends(get_db), current_doctor: Doctor = Depends(_roles)):
    hospital = resolve_hospital(db, current_doctor, hospital_id)
    try:
        return svc.add_selected(db, current_doctor, hospital, body.items)
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="The test list changed at the same moment. Nothing was saved. Please try again.")
    except Exception:
        db.rollback()
        log.exception("Add tests from master list failed")
        raise HTTPException(status_code=500, detail="Could not add the tests and nothing was saved. Please try again.")


@router.get("/template")
@limiter.limit("30/hour")
def download_select_template(request: Request, db: Session = Depends(get_db), current_doctor: Doctor = Depends(_roles)):
    data = svc.build_select_template(db)
    return StreamingResponse(io.BytesIO(data), media_type=XLSX_MIME,
                             headers={"Content-Disposition": 'attachment; filename="MedScribe_Select_Tests_Template.xlsx"'})


@router.post("/preview")
@limiter.limit("20/hour")
async def preview_select_upload(request: Request, hospital_id: Optional[int] = None, file: UploadFile = File(...),
                                db: Session = Depends(get_db), current_doctor: Doctor = Depends(_roles)):
    """Reads and checks the file against the master list and this hospital's tests. Saves NOTHING to the catalog."""
    hospital = resolve_hospital(db, current_doctor, hospital_id)
    content = await file.read(MAX_IMPORT_BYTES + 1)
    try:
        check_xlsx_bytes(file.filename, content)
        return await run_in_threadpool(svc.build_preview, db, current_doctor, hospital.id, file.filename, content)
    except ImportFileError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    except HTTPException:
        raise
    except Exception:
        log.exception("Master test select preview crashed")
        raise HTTPException(status_code=400, detail="Could not read this file. Make sure it is a valid, unprotected .xlsx made from our template.")


@router.post("/preview/{preview_id}/accept")
@limiter.limit("200/hour")
def accept_did_you_mean(request: Request, preview_id: str, body: AcceptIn, hospital_id: Optional[int] = None,
                        db: Session = Depends(get_db), current_doctor: Doctor = Depends(_roles)):
    """Click on a 'Did you mean ...?' suggestion. Only a row number and a suggested master id are sent."""
    hospital = resolve_hospital(db, current_doctor, hospital_id)
    return svc.accept_suggestion(db, current_doctor, hospital.id, preview_id, body.row, body.master_test_id)


@router.post("/confirm")
@limiter.limit("20/hour")
def confirm_select_upload(request: Request, body: ConfirmIn, hospital_id: Optional[int] = None,
                          db: Session = Depends(get_db), current_doctor: Doctor = Depends(_roles)):
    """ONE transaction, all or nothing. The browser sends only the preview id."""
    hospital = resolve_hospital(db, current_doctor, hospital_id)
    try:
        return svc.confirm_preview(db, current_doctor, hospital, body.preview_id)
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="The test list changed at the same moment. Nothing was saved. Please upload the file again.")
    except Exception:
        db.rollback()
        log.exception("Master test select confirm failed")
        raise HTTPException(status_code=500, detail="Could not add the tests and nothing was saved. Please try again.")


@router.get("/history")
def select_history(hospital_id: Optional[int] = None, db: Session = Depends(get_db),
                   current_doctor: Doctor = Depends(_roles)):
    hospital = resolve_hospital(db, current_doctor, hospital_id)
    return svc.history(db, hospital.id)


@router.post("/undo/{batch_id}")
@limiter.limit("20/hour")
def undo_select(request: Request, batch_id: int, hospital_id: Optional[int] = None, db: Session = Depends(get_db),
                current_doctor: Doctor = Depends(_roles)):
    hospital = resolve_hospital(db, current_doctor, hospital_id)
    batch = db.query(ImportBatch).filter(ImportBatch.id == batch_id, ImportBatch.hospital_id == hospital.id,
                                         ImportBatch.kind == svc.KIND).first()
    if batch is None:
        raise HTTPException(status_code=404, detail="Nothing to undo here.")
    try:
        return svc.undo_selection(db, batch, current_doctor, hospital)
    except ImportRefused as e:
        db.rollback()
        raise HTTPException(status_code=409, detail={"message": e.message, "problems": e.problems})
    except Exception:
        db.rollback()
        log.exception("Master test select undo failed")
        raise HTTPException(status_code=500, detail="Undo failed and nothing was changed.")