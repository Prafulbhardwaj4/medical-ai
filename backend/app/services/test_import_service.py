"""Database side of the lab tests Excel import: PLAN (read-only), APPLY (one transaction) and UNDO.
Writes what the manual Add Test screen writes: a main TestCatalogItem; for a panel, parameter rows
(TestCatalogParameter) that are NOT catalog tests. One deliberate difference from the manual panel
edit: parameters are matched by name and updated in place (never deleted and recreated), and a
parameter missing from the file is only deactivated."""
import json
import secrets
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy.orm import Session

from app.models.import_batch import ImportBatch, ImportBatchItem, ImportPreview
from app.models.test_catalog import TestCatalogItem
from app.models.test_catalog_parameter import TestCatalogParameter
from app.models.test_order import TestOrder
from app.services.import_common import Issue, norm_key
from app.services.test_import_parser import TestRow, tests_from_payload, tests_to_payload, TestParseResult
from app.utils.audit import stage_action
from app.utils.timezone import now_ist_naive

KIND = "tests"
PREVIEW_MINUTES = 30
_PARAM_FIELDS = ("unit", "reference_range_male", "reference_range_female", "critical_low", "critical_high",
                 "display_order", "is_active")


@dataclass
class PlannedParam:
    row: int
    name: str
    action: str                 # create / update / unchanged / deactivate
    existing: object = None
    values: dict = field(default_factory=dict)
    changes: dict = field(default_factory=dict)


@dataclass
class PlannedTest:
    row: int
    name: str
    is_panel: bool
    action: str                 # create / update / unchanged
    existing: object = None
    values: dict = field(default_factory=dict)
    changes: dict = field(default_factory=dict)
    params: list = field(default_factory=list)
    orders: int = 0


@dataclass
class TPlan:
    tests: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def has_changes(self):
        return any(t.action in ("create", "update") or any(p.action != "unchanged" for p in t.params) for t in self.tests)

    def counts(self):
        ps = [p for t in self.tests for p in t.params]
        return {
            "tests_to_create": sum(1 for t in self.tests if t.action == "create"),
            "tests_to_update": sum(1 for t in self.tests if t.action == "update"),
            "tests_unchanged": sum(1 for t in self.tests if t.action == "unchanged"),
            "params_to_create": sum(1 for p in ps if p.action == "create"),
            "params_to_update": sum(1 for p in ps if p.action == "update"),
            "params_to_deactivate": sum(1 for p in ps if p.action == "deactivate"),
            "errors": len(self.errors), "warnings": len(self.warnings),
        }


def _same(a, b):
    if a is None and b is None:
        return True
    num = (int, float)
    if isinstance(a, num) and isinstance(b, num) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(a - b) < 1e-9
    if isinstance(a, str) or isinstance(b, str):
        return (a or "") == (b or "")
    return a == b


def _diff(obj, wanted):
    return {f: v for f, v in wanted.items() if not _same(getattr(obj, f), v)}


def plan_test_import(db: Session, hospital_id: int, tests: list) -> TPlan:
    plan = TPlan()
    items = db.query(TestCatalogItem).filter(TestCatalogItem.hospital_id == hospital_id).all()
    active, inactive = {}, {}
    for t in items:
        (active if t.is_active else inactive).setdefault(norm_key(t.name), t)

    for row in tests:
        ex = active.get(row.key)
        if ex is None and row.key in inactive and row.active is False:
            continue                       # already inactive and the file says N: nothing to do
        if ex is None and row.key in inactive and row.active:
            ex = inactive[row.key]         # Active = Y in the file: reactivate it
        if ex is None and row.key in inactive:
            plan.errors.append(Issue("Tests", row.row, "Test name",
                f"'{row.name}' exists but is deactivated. Reactivate it on the Test Catalog page first, then upload again."))
            continue
        if ex is None:
            vals = {
                "name": row.name, "fee": row.price, "category": row.category, "purpose": "", "is_panel": row.is_panel,
                "reference_range_male": "" if row.is_panel else row.ref_male,
                "reference_range_female": "" if row.is_panel else row.ref_female,
                "unit": "" if row.is_panel else row.unit, "turnaround_hours": row.tat, "aliases": row.aliases,
                "critical_low": None if row.is_panel else row.crit_low,
                "critical_high": None if row.is_panel else row.crit_high,
                "fasting_required": bool(row.fasting), "required_tube": row.tube or None, "is_active": True,
            }
            pt = PlannedTest(row.row, row.name, row.is_panel, "create", values=vals)
            for p in row.params:
                pt.params.append(PlannedParam(p.row, p.name, "create", values={
                    "name": p.name, "unit": p.unit, "reference_range_male": p.ref_male,
                    "reference_range_female": p.ref_female, "purpose": "", "display_order": p.order, "is_active": True,
                    "critical_low": p.crit_low, "critical_high": p.crit_high}))
            plan.tests.append(pt)
            continue

        orders = db.query(TestOrder.id).filter(TestOrder.test_id == ex.id).count()
        if bool(ex.is_panel) != row.is_panel and orders:
            plan.errors.append(Issue("Tests", row.row, "Has parameters",
                f"'{row.name}' already has {orders} order(s), so it cannot be switched between a single test and a panel. Keep Has parameters as it is."))
            continue
        wanted = {"fee": row.price, "is_panel": row.is_panel}
        if row.category:
            wanted["category"] = row.category
        if row.tube:
            wanted["required_tube"] = row.tube
        if row.tat is not None:
            wanted["turnaround_hours"] = row.tat
        if row.aliases:
            wanted["aliases"] = row.aliases
        if row.fasting is not None:
            wanted["fasting_required"] = row.fasting
        if row.is_panel:
            if not ex.is_panel:   # single -> panel: its own range/unit/critical move to the parameters
                wanted.update({"unit": "", "reference_range_male": "", "reference_range_female": "",
                               "critical_low": None, "critical_high": None})
        else:
            for f, v in (("unit", row.unit), ("reference_range_male", row.ref_male),
                         ("reference_range_female", row.ref_female)):
                if v:
                    wanted[f] = v
            if row.crit_low is not None:
                wanted["critical_low"] = row.crit_low
            if row.crit_high is not None:
                wanted["critical_high"] = row.crit_high
        changes = _diff(ex, wanted)
        pt = PlannedTest(row.row, row.name, row.is_panel, "update" if changes else "unchanged",
                         existing=ex, changes=changes, orders=orders)

        params = db.query(TestCatalogParameter).filter(TestCatalogParameter.test_catalog_item_id == ex.id).all()
        pmap = {norm_key(p.name): p for p in params}
        if row.is_panel:
            seen = set()
            for p in row.params:
                k = norm_key(p.name)
                seen.add(k)
                cur = pmap.get(k)
                if cur is None:
                    pt.params.append(PlannedParam(p.row, p.name, "create", values={
                        "name": p.name, "unit": p.unit, "reference_range_male": p.ref_male,
                        "reference_range_female": p.ref_female, "purpose": "", "display_order": p.order,
                        "is_active": True, "critical_low": p.crit_low, "critical_high": p.crit_high}))
                    continue
                w = {"display_order": p.order, "is_active": True}
                if p.unit:
                    w["unit"] = p.unit
                if p.ref_male:
                    w["reference_range_male"] = p.ref_male
                if p.ref_female:
                    w["reference_range_female"] = p.ref_female
                if p.crit_low is not None:
                    w["critical_low"] = p.crit_low
                if p.crit_high is not None:
                    w["critical_high"] = p.crit_high
                ch = _diff(cur, w)
                pt.params.append(PlannedParam(p.row, p.name, "update" if ch else "unchanged", existing=cur, changes=ch))
            for k, cur in pmap.items():
                if k not in seen and cur.is_active:
                    pt.params.append(PlannedParam(row.row, cur.name, "deactivate", existing=cur,
                                                  changes={"is_active": False}))
                    plan.warnings.append(Issue("Tests", row.row, "Test name",
                        f"Parameter '{cur.name}' is not in the file for '{row.name}'. It will be deactivated (not deleted), so old results are kept."))
        else:
            for cur in pmap.values():
                if cur.is_active:
                    pt.params.append(PlannedParam(row.row, cur.name, "deactivate", existing=cur,
                                                  changes={"is_active": False}))
        plan.tests.append(pt)
    # --- purpose, irreplaceable sample, NABL accredited, active (and parameter purpose) ---
    by_key = {r.key: r for r in tests}
    for pt in plan.tests:
        r = by_key.get(norm_key(pt.name))
        if r is None:
            continue
        if pt.action == "create":
            pt.values["purpose"] = r.purpose
            pt.values["is_irreplaceable_sample"] = bool(r.irreplaceable)
            pt.values["is_nabl_accredited"] = bool(r.nabl)
            if r.active is not None:
                pt.values["is_active"] = r.active
        else:
            want = {}
            if r.purpose:
                want["purpose"] = r.purpose
            if r.irreplaceable is not None:
                want["is_irreplaceable_sample"] = r.irreplaceable
            if r.nabl is not None:
                want["is_nabl_accredited"] = r.nabl
            if r.active is not None:
                want["is_active"] = r.active
            more = _diff(pt.existing, {k: v for k, v in want.items() if k not in pt.changes})
            if more:
                pt.changes.update(more)
                pt.action = "update"
        pfile = {norm_key(p.name): p for p in r.params}
        for pp in pt.params:
            pr = pfile.get(norm_key(pp.name))
            if pr is None:
                continue
            if pp.action == "create":
                pp.values["purpose"] = pr.purpose
            elif pp.action in ("update", "unchanged") and pr.purpose and not _same(pp.existing.purpose, pr.purpose):
                pp.changes["purpose"] = pr.purpose
                pp.action = "update"
    return plan


def plan_to_dict(plan: TPlan, preview_limit: int = 50):
    rows = []
    for t in plan.tests:
        pc = [p for p in t.params if p.action != "unchanged"]
        rows.append({"row": t.row, "action": t.action, "name": t.name, "panel": t.is_panel,
                     "parameters": len(t.params),
                     "changes": [f"{f} -> {v}" for f, v in t.changes.items()] +
                                [f"parameter {p.name}: {p.action}" for p in pc][:8]})
    return {"counts": plan.counts(), "tests_preview": rows[:preview_limit]}


def save_preview(db: Session, doctor, hospital_id: int, file_name: str, parsed: TestParseResult) -> str:
    now = now_ist_naive()
    db.query(ImportPreview).filter(ImportPreview.expires_at < now).delete(synchronize_session=False)
    pid = secrets.token_urlsafe(24)
    db.add(ImportPreview(id=pid, hospital_id=hospital_id, doctor_id=doctor.id, kind=KIND,
                         file_name=(file_name or "")[:200], payload=json.dumps(tests_to_payload(parsed.tests)),
                         created_at=now, expires_at=now + timedelta(minutes=PREVIEW_MINUTES)))
    db.commit()
    return pid


def tests_from_preview(pv: ImportPreview) -> list:
    return tests_from_payload(json.loads(pv.payload))


def _snap(obj, fields):
    return {f: getattr(obj, f) for f in fields}


def apply_test_plan(db: Session, plan: TPlan, actor, hospital_id: int, file_name: str) -> ImportBatch:
    counts = plan.counts()
    batch = ImportBatch(hospital_id=hospital_id, kind=KIND, created_by=actor.id,
                        created_by_name=(f"{actor.title} {actor.name}" if getattr(actor, "title", None) else actor.name),
                        created_by_role=actor.role.value, file_name=(file_name or "")[:200],
                        status="applied", summary=json.dumps(counts))
    db.add(batch)
    db.flush()

    def item(entity, entity_id, action, before=None, after=None):
        db.add(ImportBatchItem(batch_id=batch.id, entity=entity, entity_id=entity_id, action=action,
                               before_json=json.dumps(before) if before is not None else None,
                               after_json=json.dumps(after) if after is not None else None))

    for pt in plan.tests:
        params_changed = any(p.action != "unchanged" for p in pt.params)
        if pt.action == "create":
            t = TestCatalogItem(hospital_id=hospital_id, **pt.values)
            db.add(t)
            db.flush()
            item("test", t.id, "created", None, {"_orders": 0, "_params_changed": params_changed})
        else:
            t = pt.existing
            if pt.action == "update":
                before = _snap(t, pt.changes.keys())
                for f, v in pt.changes.items():
                    setattr(t, f, v)
                item("test", t.id, "updated", before, dict(_snap(t, pt.changes.keys()), _orders=pt.orders, _params_changed=params_changed))
            elif params_changed:
                item("test", t.id, "updated", {}, {"_orders": pt.orders, "_params_changed": True})
        for pp in pt.params:
            if pp.action == "create":
                p = TestCatalogParameter(test_catalog_item_id=t.id, hospital_id=hospital_id, **pp.values)
                db.add(p)
                db.flush()
                item("test_parameter", p.id, "created")
            elif pp.action in ("update", "deactivate"):
                p = pp.existing
                before = _snap(p, pp.changes.keys())
                for f, v in pp.changes.items():
                    setattr(p, f, v)
                item("test_parameter", p.id, "updated", before, _snap(p, pp.changes.keys()))

    stage_action(db, actor, "test_import_applied", "import_batch", batch.id, file_name,
                 details=", ".join(f"{k}={v}" for k, v in counts.items()), hospital_id=hospital_id)
    db.commit()
    return batch


def _matches(obj, after):
    return all(_same(getattr(obj, f), v) for f, v in after.items() if not f.startswith("_"))


def undo_test_import(db: Session, batch: ImportBatch, actor) -> dict:
    from app.services.medicine_import_service import ImportRefused
    if batch.status != "applied":
        raise ImportRefused("This import was already undone.")
    latest = db.query(ImportBatch).filter(ImportBatch.hospital_id == batch.hospital_id, ImportBatch.kind == batch.kind,
                                          ImportBatch.status == "applied").order_by(ImportBatch.id.desc()).first()
    if latest is None or latest.id != batch.id:
        raise ImportRefused("Only the most recent import can be undone. Undo the newer import first.")

    items = db.query(ImportBatchItem).filter(ImportBatchItem.batch_id == batch.id).all()
    problems, tests, params = [], {}, {}
    for i in items:
        if i.entity == "test":
            t = db.query(TestCatalogItem).filter(TestCatalogItem.id == i.entity_id).first()
            if t is None:
                problems.append("A test from this import no longer exists.")
                continue
            after = json.loads(i.after_json or "{}")
            tests[t.id] = (t, i)
            orders = db.query(TestOrder.id).filter(TestOrder.test_id == t.id).count()
            if i.action == "created":
                if orders:
                    problems.append(f"{t.name} has already been ordered ({orders} order(s)).")
            else:
                if not _matches(t, after):
                    problems.append(f"{t.name} was edited after the import, so its old values cannot be restored safely.")
                if after.get("_params_changed") and orders != after.get("_orders", orders):
                    problems.append(f"{t.name} received new orders after the import, so its parameters cannot be rolled back safely.")
        elif i.entity == "test_parameter":
            p = db.query(TestCatalogParameter).filter(TestCatalogParameter.id == i.entity_id).first()
            if p is None:
                problems.append("A parameter from this import no longer exists.")
                continue
            params[p.id] = (p, i)
            if i.action == "updated" and not _matches(p, json.loads(i.after_json or "{}")):
                problems.append(f"Parameter {p.name} was edited after the import, so its old values cannot be restored safely.")
    if problems:
        raise ImportRefused("This import cannot be undone because some of it is already in use. Nothing was changed.",
                            list(dict.fromkeys(problems))[:10])

    for p, i in params.values():
        if i.action == "created":
            db.delete(p)
        else:
            for f, v in json.loads(i.before_json or "{}").items():
                setattr(p, f, v)
    db.flush()
    removed = restored = 0
    for t, i in tests.values():
        if i.action == "created":
            db.delete(t)
            removed += 1
        else:
            for f, v in json.loads(i.before_json or "{}").items():
                setattr(t, f, v)
            restored += 1
    db.flush()
    batch.status = "undone"
    batch.undone_at = now_ist_naive()
    batch.undone_by = actor.id
    stage_action(db, actor, "test_import_undone", "import_batch", batch.id, batch.file_name,
                 details=f"tests_removed={removed}, tests_restored={restored}, parameter_rows={len(params)}",
                 hospital_id=batch.hospital_id)
    db.commit()
    return {"tests_removed": removed, "tests_restored": restored, "parameter_rows": len(params)}