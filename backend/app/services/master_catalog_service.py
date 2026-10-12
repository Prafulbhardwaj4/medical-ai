"""Platform-wide master lists (tests and medicines), kept by the Super Admin.
CRUD helpers, and the Excel master-list upload: PLAN (read-only) -> PREVIEW -> APPLY (one transaction).
Master items have no price, no brand, no stock, and are never deleted (only deactivated)."""
import io
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.master_import_preview import MasterImportPreview
from app.models.master_medicine import MasterMedicine
from app.models.master_test import MasterTest, MasterTestParameter
from app.routers.medicines import VALID_BILLING_MODES, VALID_SCHEDULES, MAX_PACK_SIZE
from app.services.import_common import ImportFileError, Issue, is_blank, norm_key, norm_strength_key, read_table
from app.services.medicine_import_parser import (
    FORMS, GST_CHOICES, MAX_MEDICINE_ROWS, MED_COLUMNS, MedRow, MedicineParseResult, _parse_medicine_row,
)
from app.services.test_import_parser import TestRow, tests_from_payload, tests_to_payload
from app.utils.audit import stage_action
from app.utils.master_catalog import clean_text, medicine_display_name, norm_name
from app.utils.timezone import now_ist_naive

PREVIEW_MINUTES = 30
_FORM_LOOKUP = {f.casefold(): f for f in FORMS}

# HIV and radiology never live in the master list. Name/category based guard.
_EXCLUDED_RE = re.compile(
    r"\b(hiv|immunodeficiency|x[\s-]?rays?|ultrasound|ultrasonography|sonography|usg|mri|ct[\s-]?scan|"
    r"pet[\s-]?scan|mammograph\w*|doppler|imaging|radiolog\w*)\b", re.IGNORECASE)


def is_excluded_test(name, category=None) -> bool:
    return bool(_EXCLUDED_RE.search(f"{name or ''} {category or ''}"))


# ======================= test payloads / validation =======================

class MasterParamIn(BaseModel):
    name: str
    unit: Optional[str] = ""
    reference_range_male: Optional[str] = ""
    reference_range_female: Optional[str] = ""
    purpose: Optional[str] = ""
    critical_low: Optional[float] = None
    critical_high: Optional[float] = None


class MasterTestIn(BaseModel):
    test_name: str
    category: Optional[str] = ""
    aliases: Optional[str] = ""
    required_tube: Optional[str] = ""
    fasting_required: Optional[bool] = False
    turnaround_hours: Optional[int] = None
    is_panel: Optional[bool] = False
    purpose: Optional[str] = ""
    unit: Optional[str] = ""
    reference_range_male: Optional[str] = ""
    reference_range_female: Optional[str] = ""
    critical_low: Optional[float] = None
    critical_high: Optional[float] = None
    parameters: Optional[list[MasterParamIn]] = None


class MasterMedicineIn(BaseModel):
    generic_name: str
    strength: str
    dosage_form: str
    schedule: Optional[str] = "otc"
    default_pack_size: Optional[int] = 1
    default_billing_mode: Optional[str] = "per_unit"
    gst_percent: Optional[float] = None
    hsn_code: Optional[str] = ""
    category: Optional[str] = ""


def _bad(msg):
    raise HTTPException(status_code=400, detail=msg)


def _limit(value, maxlen, label):
    s = clean_text(value)
    if len(s) > maxlen:
        _bad(f"{label} is too long (maximum {maxlen} characters)")
    return s


def clean_test_payload(p: MasterTestIn) -> dict:
    name = clean_text(p.test_name)
    if not name or len(name) > 150:
        _bad("Test name is required (150 characters max)")
    category = _limit(p.category, 100, "Category")
    if is_excluded_test(name, category):
        _bad("HIV and radiology tests are not kept in the master list.")
    tat = p.turnaround_hours
    if tat is not None and not (1 <= tat <= 10000):
        _bad("Turnaround hours must be between 1 and 10,000")
    is_panel = bool(p.is_panel)
    params = []
    if is_panel:
        seen = set()
        for prm in (p.parameters or []):
            pname = clean_text(prm.name)
            if not pname:
                continue
            if len(pname) > 150:
                _bad(f"Parameter '{pname[:30]}' name is too long (150 characters max)")
            if pname.lower() in seen:
                _bad(f"Parameter '{pname}' is listed twice in this panel")
            seen.add(pname.lower())
            if prm.critical_low is not None and prm.critical_high is not None and prm.critical_low >= prm.critical_high:
                _bad(f"Parameter '{pname}': critical low must be less than critical high")
            params.append({
                "name": pname, "unit": _limit(prm.unit, 50, "Unit"),
                "reference_range_male": _limit(prm.reference_range_male, 200, "Reference range"),
                "reference_range_female": _limit(prm.reference_range_female, 200, "Reference range"),
                "purpose": _limit(prm.purpose, 1000, "Purpose"),
                "critical_low": prm.critical_low, "critical_high": prm.critical_high,
                "display_order": len(params),
            })
        if not params:
            _bad("A panel needs at least one parameter")
    elif p.critical_low is not None and p.critical_high is not None and p.critical_low >= p.critical_high:
        _bad("Critical low must be less than critical high")
    return {
        "name": name, "category": category or None,
        "aliases": _limit(p.aliases, 500, "Other names") or None,
        "required_tube": _limit(p.required_tube, 100, "Sample tube") or None,
        "fasting_required": bool(p.fasting_required), "turnaround_hours": tat, "is_panel": is_panel,
        "purpose": _limit(p.purpose, 1000, "Purpose") or None,
        "unit": "" if is_panel else _limit(p.unit, 50, "Unit"),
        "reference_range_male": "" if is_panel else _limit(p.reference_range_male, 200, "Reference range"),
        "reference_range_female": "" if is_panel else _limit(p.reference_range_female, 200, "Reference range"),
        "critical_low": None if is_panel else p.critical_low,
        "critical_high": None if is_panel else p.critical_high,
        "params": params,
    }


def clean_medicine_payload(p: MasterMedicineIn) -> dict:
    generic = clean_text(p.generic_name)
    strength = clean_text(p.strength)
    if not generic or len(generic) > 200:
        _bad("Generic name is required (200 characters max)")
    if not strength or len(strength) > 50:
        _bad("Strength is required (50 characters max)")
    form = _FORM_LOOKUP.get(clean_text(p.dosage_form).casefold())
    if not form:
        _bad(f"Form must be one of: {', '.join(FORMS)}")
    schedule = (p.schedule or "otc").strip().lower()
    if schedule not in VALID_SCHEDULES:
        _bad("Invalid schedule")
    mode = (p.default_billing_mode or "per_unit").strip().lower()
    if mode not in VALID_BILLING_MODES:
        _bad("Invalid billing mode")
    pack = p.default_pack_size or 1
    if not (1 <= pack <= MAX_PACK_SIZE):
        _bad(f"Units per pack must be between 1 and {MAX_PACK_SIZE:,}")
    if p.gst_percent is None or p.gst_percent not in GST_CHOICES:
        _bad(f"GST % must be one of {', '.join(str(g) for g in GST_CHOICES)}")
    return {
        "generic_name": generic, "strength": strength, "dosage_form": form, "schedule": schedule,
        "default_pack_size": pack, "default_billing_mode": mode, "gst_percent": float(p.gst_percent),
        "hsn_code": _limit(p.hsn_code, 20, "HSN code") or None,
        "category": _limit(p.category, 100, "Category") or None,
    }


def test_name_conflict(db: Session, name: str, exclude_id=None):
    q = db.query(MasterTest.id).filter(MasterTest.name_norm == norm_name(name))
    if exclude_id:
        q = q.filter(MasterTest.id != exclude_id)
    return q.first() is not None


def medicine_conflict(db: Session, generic, strength, form, exclude_id=None):
    """Same generic + form + strength (spaces ignored, so '500 mg' equals '500mg')."""
    q = db.query(MasterMedicine).filter(
        func.lower(MasterMedicine.generic_name) == clean_text(generic).lower(),
        func.lower(MasterMedicine.dosage_form) == clean_text(form).lower())
    if exclude_id:
        q = q.filter(MasterMedicine.id != exclude_id)
    want = norm_strength_key(strength)
    return any(norm_strength_key(m.strength) == want for m in q.all())


# ======================= serializers =======================

def serialize_param(p: MasterTestParameter) -> dict:
    return {"id": p.id, "name": p.name, "unit": p.unit or "",
            "reference_range_male": p.reference_range_male or "",
            "reference_range_female": p.reference_range_female or "",
            "purpose": p.purpose or "", "critical_low": p.critical_low, "critical_high": p.critical_high,
            "display_order": p.display_order}


def serialize_test(t: MasterTest, db: Session = None, param_count: Optional[int] = None) -> dict:
    out = {"id": t.id, "test_name": t.name, "category": t.category or "", "is_panel": t.is_panel,
           "is_active": t.is_active, "parameter_count": param_count or 0}
    if db is not None:
        rows = db.query(MasterTestParameter).filter(
            MasterTestParameter.master_test_id == t.id, MasterTestParameter.is_active == True  # noqa: E712
        ).order_by(MasterTestParameter.display_order, MasterTestParameter.id).all()
        out["parameters"] = [serialize_param(p) for p in rows]
        out["parameter_count"] = len(rows)
        out.update({"aliases": t.aliases or "", "required_tube": t.required_tube or "",
                    "fasting_required": t.fasting_required, "turnaround_hours": t.turnaround_hours,
                    "purpose": t.purpose or "", "unit": t.unit or "",
                    "reference_range_male": t.reference_range_male or "",
                    "reference_range_female": t.reference_range_female or "",
                    "critical_low": t.critical_low, "critical_high": t.critical_high})
    return out


def serialize_medicine(m: MasterMedicine) -> dict:
    return {"id": m.id, "display_name": m.display_name, "generic_name": m.generic_name,
            "strength": m.strength or "", "dosage_form": m.dosage_form or "", "schedule": m.schedule,
            "default_pack_size": m.default_pack_size, "default_billing_mode": m.default_billing_mode,
            "gst_percent": m.gst_percent, "hsn_code": m.hsn_code or "", "category": m.category or "",
            "is_active": m.is_active}


# ======================= Excel master-list upload =======================

_IGNORED_MED_KEYS = ("brand", "price", "nppa", "threshold")


def parse_master_medicines_workbook(content: bytes) -> MedicineParseResult:
    """Same Medicines sheet and columns as the hospital import. Brand, MRP, NPPA and low-stock cells
    are ignored (the master list has no price and no brand). Reuses the hospital row checker."""
    import openpyxl
    result = MedicineParseResult()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception:
        raise ImportFileError("Could not read this file. Make sure it is a valid, unprotected .xlsx.")
    cols = [(k, l, r and k not in _IGNORED_MED_KEYS) for k, l, r in MED_COLUMNS]
    try:
        rows = read_table(wb, "Medicines", cols, MAX_MEDICINE_ROWS, result.errors, True)
    finally:
        wb.close()
    result.medicine_rows_read = len(rows or [])
    if rows is not None and not rows:
        result.errors.append(Issue("Medicines", None, None, "The Medicines sheet has no rows."))
    ignored, parsed = False, []
    for n, v in rows or []:
        v = dict(v)
        if any(not is_blank(v[k]) for k in _IGNORED_MED_KEYS):
            ignored = True
        v.update({"brand": None, "price": 1, "nppa": None, "threshold": None})
        m = _parse_medicine_row(n, v, result)
        if m:
            parsed.append(m)
    if ignored:
        result.warnings.append(Issue("Medicines", None, None,
            "Brand name, MRP per pack, NPPA ceiling and Low-stock alert are not part of the master list. Those cells were ignored."))
    seen = {}
    for m in parsed:
        if m.group_key in seen:
            result.errors.append(Issue("Medicines", m.row, "Generic name",
                f"Duplicate of row {seen[m.group_key]} (same generic name, strength and form). Keep one row."))
            continue
        seen[m.group_key] = m.row
        result.medicines.append(m)
    return result


@dataclass
class MPlanItem:
    row: int
    name: str
    action: str                      # create / update / unchanged / ignored
    existing: object = None
    values: dict = field(default_factory=dict)      # fields to set on create
    changes: dict = field(default_factory=dict)     # fields to set on update
    params: Optional[list] = None                   # tests only: full parameter list when it must be (re)written
    is_panel: bool = False
    note: str = ""


@dataclass
class MPlan:
    kind: str
    items: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def has_changes(self):
        return any(i.action in ("create", "update") for i in self.items)

    def counts(self):
        c = {a: sum(1 for i in self.items if i.action == a) for a in ("create", "update", "unchanged", "ignored")}
        return {"to_create": c["create"], "to_update": c["update"], "unchanged": c["unchanged"],
                "ignored": c["ignored"], "errors": len(self.errors), "warnings": len(self.warnings)}


def _same(a, b):
    if a is None and b is None:
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(a - b) < 1e-9
    if isinstance(a, str) or isinstance(b, str):
        return (a or "") == (b or "")
    return a == b


def _diff(obj, wanted):
    return {f: v for f, v in wanted.items() if not _same(getattr(obj, f), v)}


def _param_sig(d):
    def num(x):
        return None if x is None else round(float(x), 6)
    return (norm_name(d["name"]), d.get("unit") or "", d.get("reference_range_male") or "",
            d.get("reference_range_female") or "", d.get("purpose") or "",
            num(d.get("critical_low")), num(d.get("critical_high")), d.get("display_order", 0))


def plan_master_tests(db: Session, tests: list) -> MPlan:
    plan = MPlan("tests")
    existing = {t.name_norm: t for t in db.query(MasterTest).all()}
    pmap = {}
    for p in db.query(MasterTestParameter).filter(MasterTestParameter.is_active == True).order_by(  # noqa: E712
            MasterTestParameter.display_order, MasterTestParameter.id).all():
        pmap.setdefault(p.master_test_id, []).append(p)
    for row in tests:
        if is_excluded_test(row.name, row.category):
            plan.warnings.append(Issue("Tests", row.row, "Test name",
                f"'{row.name}' looks like an HIV or radiology test. These are never kept in the master list, so it was ignored."))
            plan.items.append(MPlanItem(row.row, row.name, "ignored", is_panel=row.is_panel))
            continue
        wanted_params = [{"name": p.name, "unit": p.unit or "", "reference_range_male": p.ref_male or "",
                          "reference_range_female": p.ref_female or "", "purpose": p.purpose or "",
                          "critical_low": p.crit_low, "critical_high": p.crit_high, "display_order": i}
                         for i, p in enumerate(row.params)] if row.is_panel else []
        ex = existing.get(norm_name(row.name))
        if ex is None:
            vals = {"name": row.name, "category": row.category or None, "required_tube": row.tube or None,
                    "fasting_required": bool(row.fasting), "turnaround_hours": row.tat,
                    "aliases": row.aliases or None, "purpose": row.purpose or None, "is_panel": row.is_panel,
                    "unit": "" if row.is_panel else row.unit,
                    "reference_range_male": "" if row.is_panel else row.ref_male,
                    "reference_range_female": "" if row.is_panel else row.ref_female,
                    "critical_low": None if row.is_panel else row.crit_low,
                    "critical_high": None if row.is_panel else row.crit_high,
                    "is_active": True if row.active is None else row.active}
            plan.items.append(MPlanItem(row.row, row.name, "create", values=vals, params=wanted_params, is_panel=row.is_panel))
            continue
        want = {"is_panel": row.is_panel}
        for f, v in (("category", row.category), ("required_tube", row.tube), ("aliases", row.aliases), ("purpose", row.purpose)):
            if v:
                want[f] = v
        if row.tat is not None:
            want["turnaround_hours"] = row.tat
        if row.fasting is not None:
            want["fasting_required"] = row.fasting
        if row.active is not None:
            want["is_active"] = row.active
        if row.is_panel:
            want.update({"unit": "", "reference_range_male": "", "reference_range_female": "",
                         "critical_low": None, "critical_high": None})
        else:
            for f, v in (("unit", row.unit), ("reference_range_male", row.ref_male), ("reference_range_female", row.ref_female)):
                if v:
                    want[f] = v
            if row.crit_low is not None:
                want["critical_low"] = row.crit_low
            if row.crit_high is not None:
                want["critical_high"] = row.crit_high
        changes = _diff(ex, want)
        cur_sigs = [_param_sig(serialize_param(p)) for p in pmap.get(ex.id, [])]
        new_sigs = [_param_sig(d) for d in wanted_params]
        params = wanted_params if cur_sigs != new_sigs else None
        action = "update" if (changes or params is not None) else "unchanged"
        plan.items.append(MPlanItem(row.row, row.name, action, existing=ex, changes=changes, params=params, is_panel=row.is_panel))
    return plan


def plan_master_medicines(db: Session, meds: list) -> MPlan:
    plan = MPlan("medicines")
    existing = {(norm_key(m.generic_name), norm_strength_key(m.strength), norm_key(m.dosage_form)): m
                for m in db.query(MasterMedicine).all()}
    for r in meds:
        name = medicine_display_name(r.generic, r.strength, r.form)
        ex = existing.get(r.group_key)
        if ex is None:
            vals = {"generic_name": r.generic, "strength": r.strength, "dosage_form": r.form, "schedule": r.schedule,
                    "default_pack_size": r.pack_size, "default_billing_mode": r.billing_mode,
                    "gst_percent": float(r.gst), "hsn_code": r.hsn or None, "category": r.category or None,
                    "is_active": bool(r.active)}
            plan.items.append(MPlanItem(r.row, name, "create", values=vals))
            continue
        want = {"schedule": r.schedule, "default_pack_size": r.pack_size, "default_billing_mode": r.billing_mode,
                "gst_percent": float(r.gst)}
        if r.hsn:
            want["hsn_code"] = r.hsn
        if r.category:
            want["category"] = r.category
        if r.active is False and ex.is_active:
            want["is_active"] = False
        if not ex.is_active and r.active:
            plan.warnings.append(Issue("Medicines", r.row, "Active",
                f"'{ex.display_name}' is inactive in the master list. An upload does not reactivate it. Use the Active switch."))
        changes = _diff(ex, want)
        plan.items.append(MPlanItem(r.row, ex.display_name, "update" if changes else "unchanged", existing=ex, changes=changes))
    return plan


def plan_to_dict(plan: MPlan, preview_limit: int = 200) -> dict:
    rows = [{"row": i.row, "name": i.name, "action": i.action,
             "panel": i.is_panel if plan.kind == "tests" else None,
             "changes": [f"{f} -> {v}" for f, v in i.changes.items()][:8]
                        + (["parameters rewritten"] if i.params is not None and i.action == "update" else [])}
            for i in plan.items[:preview_limit]]
    return {"counts": plan.counts(), "rows": rows, "rows_shown": len(rows), "rows_total": len(plan.items)}


def preview_payload_to_plan(db: Session, kind: str, payload: str) -> MPlan:
    data = json.loads(payload)
    if kind == "tests":
        return plan_master_tests(db, tests_from_payload(data))
    return plan_master_medicines(db, [MedRow(**d) for d in data])


def build_preview(db: Session, doctor, kind: str, file_name: str, content: bytes) -> dict:
    """Parse + plan + (if clean) store the parsed rows on the server. Nothing is saved to the master tables."""
    if kind == "tests":
        from app.services.test_import_parser import parse_tests_workbook
        parsed = parse_tests_workbook(content, master=True)
        plan = plan_master_tests(db, parsed.tests)
        payload = json.dumps(tests_to_payload(parsed.tests))
    else:
        parsed = parse_master_medicines_workbook(content)
        plan = plan_master_medicines(db, parsed.medicines)
        payload = json.dumps([m.to_dict() for m in parsed.medicines])
    errors = [i.to_dict() for i in parsed.errors] + [i.to_dict() for i in plan.errors]
    warnings = [i.to_dict() for i in parsed.warnings] + [i.to_dict() for i in plan.warnings]
    result = plan_to_dict(plan)
    result["counts"]["errors"] = len(errors)
    result["counts"]["warnings"] = len(warnings)
    result.update({"ok": not errors, "kind": kind, "file_name": file_name, "errors": errors, "warnings": warnings,
                   "preview_id": None, "expires_in_minutes": PREVIEW_MINUTES,
                   "nothing_to_change": (not errors) and (not plan.has_changes())})
    if not errors and plan.has_changes():
        now = now_ist_naive()
        db.query(MasterImportPreview).filter(MasterImportPreview.expires_at < now).delete(synchronize_session=False)
        pid = secrets.token_urlsafe(24)
        db.add(MasterImportPreview(id=pid, doctor_id=doctor.id, kind=kind, file_name=(file_name or "")[:200],
                                   payload=payload, created_at=now, expires_at=now + timedelta(minutes=PREVIEW_MINUTES)))
        db.commit()
        result["preview_id"] = pid
    return result


def apply_plan(db: Session, plan: MPlan, actor, file_name: str) -> dict:
    """One transaction: every create/update plus the audit row, or nothing."""
    counts = plan.counts()
    for it in plan.items:
        if it.action == "ignored" or it.action == "unchanged":
            continue
        if plan.kind == "tests":
            if it.action == "create":
                t = MasterTest(**it.values)
                db.add(t)
                db.flush()
            else:
                t = it.existing
                for f, v in it.changes.items():
                    setattr(t, f, v)
            if it.params is not None:
                db.query(MasterTestParameter).filter(MasterTestParameter.master_test_id == t.id).delete(synchronize_session=False)
                for d in it.params:
                    db.add(MasterTestParameter(master_test_id=t.id, is_active=True, **d))
        else:
            if it.action == "create":
                db.add(MasterMedicine(**it.values))
            else:
                for f, v in it.changes.items():
                    setattr(it.existing, f, v)
    stage_action(db, actor, f"master_{plan.kind}_import_applied", "master_catalog", None, file_name,
                 details=", ".join(f"{k}={v}" for k, v in counts.items()), hospital_id=None)
    db.commit()
    return counts