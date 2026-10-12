"""Super Admin only: the platform-wide MASTER lists of tests and medicines (no price, never deleted,
only deactivated). Hospitals copy items out of these lists; later edits here never change a hospital's rows."""
import io
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.database import get_db
from app.models.doctor import Doctor
from app.models.master_import_preview import MasterImportPreview
from app.models.master_medicine import MasterMedicine
from app.models.master_test import MasterTest, MasterTestParameter
from app.services import master_catalog_service as svc
from app.services.import_common import ImportFileError, MAX_IMPORT_BYTES, XLSX_MIME, check_xlsx_bytes
from app.services.medicine_import_parser import BILLING_CHOICES, FORMS, GST_CHOICES, SCHEDULE_CHOICES
from app.services.medicine_import_template import build_medicine_template
from app.services.test_import_template import build_test_template
from app.utils.audit import stage_action
from app.utils.master_catalog import clean_text
from app.utils.rate_limit import limiter
from app.utils.roles import require_super_admin
from app.utils.timezone import now_ist_naive

router = APIRouter(prefix="/superadmin/master", tags=["superadmin-master-catalogs"])
log = logging.getLogger(__name__)
KINDS = ("tests", "medicines")


class ActiveIn(BaseModel):
    is_active: bool


class ConfirmIn(BaseModel):
    preview_id: str


def _kind(kind: str) -> str:
    if kind not in KINDS:
        raise HTTPException(status_code=404, detail="Unknown master list.")
    return kind


def _status_filter(query, column, status: str):
    if status == "active":
        return query.filter(column == True)  # noqa: E712
    if status == "inactive":
        return query.filter(column == False)  # noqa: E712
    return query


# ----------------------------- master tests -----------------------------

@router.get("/tests")
def list_master_tests(search: Optional[str] = None, category: Optional[str] = None, status: str = "all",
                      limit: int = Query(1000, ge=1, le=5000), offset: int = Query(0, ge=0),
                      db: Session = Depends(get_db), current_doctor: Doctor = Depends(require_super_admin)):
    q = _status_filter(db.query(MasterTest), MasterTest.is_active, status)
    if category:
        q = q.filter(MasterTest.category == category)
    if search and search.strip():
        s = clean_text(search).lower()
        q = q.filter(func.lower(MasterTest.name).contains(s, autoescape=True)
                     | func.lower(func.coalesce(MasterTest.aliases, "")).contains(s, autoescape=True))
    total = q.count()
    items = q.order_by(func.lower(MasterTest.name)).offset(offset).limit(limit).all()
    counts = dict(db.query(MasterTestParameter.master_test_id, func.count(MasterTestParameter.id)).filter(
        MasterTestParameter.is_active == True,  # noqa: E712
        MasterTestParameter.master_test_id.in_([t.id for t in items] or [0])).group_by(MasterTestParameter.master_test_id).all())
    return {"total": total, "items": [svc.serialize_test(t, None, counts.get(t.id, 0)) for t in items]}


@router.get("/tests/categories")
def master_test_categories(db: Session = Depends(get_db), current_doctor: Doctor = Depends(require_super_admin)):
    rows = db.query(MasterTest.category).filter(MasterTest.category != None, MasterTest.category != "").distinct().all()  # noqa: E711
    return sorted({r[0] for r in rows}, key=str.lower)


@router.get("/tests/{test_id}")
def get_master_test(test_id: int, db: Session = Depends(get_db), current_doctor: Doctor = Depends(require_super_admin)):
    t = db.query(MasterTest).filter(MasterTest.id == test_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Master test not found")
    return svc.serialize_test(t, db)


def _write_test(db, t: MasterTest, data: dict):
    params = data.pop("params")
    for f, v in data.items():
        setattr(t, f, v)
    db.add(t)
    db.flush()
    db.query(MasterTestParameter).filter(MasterTestParameter.master_test_id == t.id).delete(synchronize_session=False)
    for d in params:
        db.add(MasterTestParameter(master_test_id=t.id, is_active=True, **d))


@router.post("/tests", status_code=201)
def create_master_test(payload: svc.MasterTestIn, db: Session = Depends(get_db),
                       current_doctor: Doctor = Depends(require_super_admin)):
    data = svc.clean_test_payload(payload)
    if svc.test_name_conflict(db, data["name"]):
        raise HTTPException(status_code=409, detail=f"A master test named '{data['name']}' already exists")
    t = MasterTest(is_active=True)
    try:
        _write_test(db, t, data)
        stage_action(db, current_doctor, "master_test_created", "master_test", t.id, t.name, hospital_id=None)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A master test with this name already exists")
    db.refresh(t)
    return svc.serialize_test(t, db)


@router.put("/tests/{test_id}")
def update_master_test(test_id: int, payload: svc.MasterTestIn, db: Session = Depends(get_db),
                       current_doctor: Doctor = Depends(require_super_admin)):
    t = db.query(MasterTest).filter(MasterTest.id == test_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Master test not found")
    data = svc.clean_test_payload(payload)
    if svc.test_name_conflict(db, data["name"], exclude_id=t.id):
        raise HTTPException(status_code=409, detail=f"A master test named '{data['name']}' already exists")
    try:
        _write_test(db, t, data)
        stage_action(db, current_doctor, "master_test_updated", "master_test", t.id, t.name, hospital_id=None)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A master test with this name already exists")
    db.refresh(t)
    return svc.serialize_test(t, db)


@router.patch("/tests/{test_id}/active")
def set_master_test_active(test_id: int, body: ActiveIn, db: Session = Depends(get_db),
                           current_doctor: Doctor = Depends(require_super_admin)):
    t = db.query(MasterTest).filter(MasterTest.id == test_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Master test not found")
    t.is_active = body.is_active
    stage_action(db, current_doctor, "master_test_activated" if body.is_active else "master_test_deactivated",
                 "master_test", t.id, t.name, hospital_id=None)
    db.commit()
    return {"id": t.id, "is_active": t.is_active}


# ----------------------------- master medicines -----------------------------

@router.get("/medicines/meta")
def master_medicine_meta(current_doctor: Doctor = Depends(require_super_admin)):
    return {"forms": FORMS, "schedules": ["otc", "h", "h1", "x"], "schedule_labels": SCHEDULE_CHOICES,
            "billing_modes": ["per_pack", "per_unit"], "billing_labels": BILLING_CHOICES, "gst_choices": GST_CHOICES}


@router.get("/medicines")
def list_master_medicines(search: Optional[str] = None, schedule: Optional[str] = None, form: Optional[str] = None,
                          status: str = "all", limit: int = Query(1000, ge=1, le=5000), offset: int = Query(0, ge=0),
                          db: Session = Depends(get_db), current_doctor: Doctor = Depends(require_super_admin)):
    q = _status_filter(db.query(MasterMedicine), MasterMedicine.is_active, status)
    if schedule:
        q = q.filter(MasterMedicine.schedule == schedule.lower())
    if form:
        q = q.filter(MasterMedicine.dosage_form == form)
    if search and search.strip():
        q = q.filter(func.lower(MasterMedicine.display_name).contains(clean_text(search).lower(), autoescape=True))
    total = q.count()
    items = q.order_by(func.lower(MasterMedicine.display_name)).offset(offset).limit(limit).all()
    return {"total": total, "items": [svc.serialize_medicine(m) for m in items]}


@router.get("/medicines/{medicine_id}")
def get_master_medicine(medicine_id: int, db: Session = Depends(get_db), current_doctor: Doctor = Depends(require_super_admin)):
    m = db.query(MasterMedicine).filter(MasterMedicine.id == medicine_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Master medicine not found")
    return svc.serialize_medicine(m)


@router.post("/medicines", status_code=201)
def create_master_medicine(payload: svc.MasterMedicineIn, db: Session = Depends(get_db),
                           current_doctor: Doctor = Depends(require_super_admin)):
    data = svc.clean_medicine_payload(payload)
    if svc.medicine_conflict(db, data["generic_name"], data["strength"], data["dosage_form"]):
        raise HTTPException(status_code=409, detail="This medicine (same name, strength and form) is already in the master list")
    m = MasterMedicine(is_active=True, **data)
    try:
        db.add(m)
        db.flush()
        stage_action(db, current_doctor, "master_medicine_created", "master_medicine", m.id, m.display_name, hospital_id=None)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This medicine is already in the master list")
    db.refresh(m)
    return svc.serialize_medicine(m)


@router.put("/medicines/{medicine_id}")
def update_master_medicine(medicine_id: int, payload: svc.MasterMedicineIn, db: Session = Depends(get_db),
                           current_doctor: Doctor = Depends(require_super_admin)):
    m = db.query(MasterMedicine).filter(MasterMedicine.id == medicine_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Master medicine not found")
    data = svc.clean_medicine_payload(payload)
    if svc.medicine_conflict(db, data["generic_name"], data["strength"], data["dosage_form"], exclude_id=m.id):
        raise HTTPException(status_code=409, detail="This medicine (same name, strength and form) is already in the master list")
    try:
        for f, v in data.items():
            setattr(m, f, v)
        db.flush()
        stage_action(db, current_doctor, "master_medicine_updated", "master_medicine", m.id, m.display_name, hospital_id=None)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This medicine is already in the master list")
    db.refresh(m)
    return svc.serialize_medicine(m)


@router.patch("/medicines/{medicine_id}/active")
def set_master_medicine_active(medicine_id: int, body: ActiveIn, db: Session = Depends(get_db),
                               current_doctor: Doctor = Depends(require_super_admin)):
    m = db.query(MasterMedicine).filter(MasterMedicine.id == medicine_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Master medicine not found")
    m.is_active = body.is_active
    stage_action(db, current_doctor, "master_medicine_activated" if body.is_active else "master_medicine_deactivated",
                 "master_medicine", m.id, m.display_name, hospital_id=None)
    db.commit()
    return {"id": m.id, "is_active": m.is_active}


# ----------------------------- Excel master-list upload -----------------------------

@router.get("/template/{kind}")
@limiter.limit("30/hour")
def master_template(request: Request, kind: str, current_doctor: Doctor = Depends(require_super_admin)):
    _kind(kind)
    data = build_medicine_template() if kind == "medicines" else build_test_template()
    name = "MedScribe_Master_Medicines_Template.xlsx" if kind == "medicines" else "MedScribe_Master_Tests_Template.xlsx"
    return StreamingResponse(io.BytesIO(data), media_type=XLSX_MIME,
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/{kind}/preview")
@limiter.limit("20/hour")
async def master_preview(request: Request, kind: str, file: UploadFile = File(...), db: Session = Depends(get_db),
                         current_doctor: Doctor = Depends(require_super_admin)):
    _kind(kind)
    content = await file.read(MAX_IMPORT_BYTES + 1)
    try:
        check_xlsx_bytes(file.filename, content)
        return await run_in_threadpool(svc.build_preview, db, current_doctor, kind, file.filename, content)
    except ImportFileError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    except HTTPException:
        raise
    except Exception:
        log.exception("Master list preview crashed")
        raise HTTPException(status_code=400, detail="Could not read this file. Make sure it is a valid, unprotected .xlsx made from our template.")


@router.post("/{kind}/confirm")
@limiter.limit("20/hour")
def master_confirm(request: Request, kind: str, body: ConfirmIn, db: Session = Depends(get_db),
                   current_doctor: Doctor = Depends(require_super_admin)):
    _kind(kind)
    pv = db.query(MasterImportPreview).filter(MasterImportPreview.id == body.preview_id).first()
    if pv is None or pv.kind != kind or pv.doctor_id != current_doctor.id:
        raise HTTPException(status_code=404, detail="Preview not found. Please upload the file again.")
    if pv.consumed:
        raise HTTPException(status_code=400, detail="This preview was already imported. Upload the file again if you need to repeat it.")
    if pv.expires_at < now_ist_naive():
        raise HTTPException(status_code=400, detail="This preview expired. Please upload the file again.")
    plan = svc.preview_payload_to_plan(db, kind, pv.payload)
    if plan.errors:
        raise HTTPException(status_code=409, detail={
            "message": "The master list changed since the preview, so the file no longer fits. Nothing was saved. Upload the file again.",
            "errors": [i.to_dict() for i in plan.errors]})
    if not plan.has_changes():
        raise HTTPException(status_code=400, detail="Nothing to import: everything in this file is already in the master list.")
    claimed = db.query(MasterImportPreview).filter(MasterImportPreview.id == pv.id, MasterImportPreview.consumed == False).update(  # noqa: E712
        {"consumed": True}, synchronize_session=False)
    if claimed != 1:
        db.rollback()
        raise HTTPException(status_code=400, detail="This preview was already imported.")
    try:
        counts = svc.apply_plan(db, plan, current_doctor, pv.file_name)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="The master list changed at the same moment. Nothing was saved. Please upload the file again.")
    except Exception:
        db.rollback()
        log.exception("Master list import apply failed")
        raise HTTPException(status_code=500, detail="Import failed and nothing was saved. Please try again.")
    return {"summary": counts}