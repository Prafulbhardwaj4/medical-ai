"""Database side of the medicines Excel import: PLAN (read-only, used for the preview and again
at confirm time), APPLY (one transaction, all or nothing) and UNDO.
The structure created is the same as the manual flows: a generic (parent) row, brand rows under it
(like 'Add brand'), batches on the row that is sold, stock_quantity = sum of batches."""
import json
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.admission import AdmissionMedicationOrder
from app.models.hospital_medicine import HospitalMedicine
from app.models.import_batch import ImportBatch, ImportBatchItem, ImportPreview
from app.models.medicine_batch import MedicineBatch
from app.models.medicine_order import MedicineOrder
from app.models.medicine_order_batch import MedicineOrderBatch
from app.routers.medicines import compute_unit_price
from app.services.import_common import Issue, norm_key, norm_strength_key
from app.services.medicine_import_parser import (
    MedRow, StockRow, MedicineParseResult, MAX_BATCH_UNITS,
)
from app.utils.audit import stage_action
from app.utils.auth import ist_today
from app.utils.timezone import now_ist_naive

PREVIEW_MINUTES = 30
SCHEDULE_CHANGERS = ("admin", "sub_admin", "super_admin")   # same rule as update_medicine
KIND = "medicines"
_CASCADE = ["schedule", "gst_percent", "hsn_code", "nppa_ceiling_price"]   # what update_medicine copies to brands


class ImportRefused(Exception):
    def __init__(self, message, problems=None):
        super().__init__(message)
        self.message = message
        self.problems = problems or []


# ---------- plan objects ----------

@dataclass
class PlannedMed:
    key: tuple
    row: int
    is_parent: bool
    action: str                      # create / update / unchanged
    label: str
    existing: object = None          # HospitalMedicine or None
    parent_key: tuple = None
    values: dict = field(default_factory=dict)    # full values for a create
    changes: dict = field(default_factory=dict)   # field -> new value for an update
    in_file: bool = True


@dataclass
class PlannedBatch:
    row: int
    med_key: tuple
    action: str                      # create / skip
    batch: str
    units: int
    expiry: date
    received: date
    expired: bool


@dataclass
class Plan:
    meds: list = field(default_factory=list)
    batches: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def has_changes(self):
        return any(m.action in ("create", "update") for m in self.meds) or any(b.action == "create" for b in self.batches)

    def counts(self):
        meds_file = [m for m in self.meds if m.in_file]
        return {
            "medicines_to_create": sum(1 for m in self.meds if m.action == "create"),
            "medicines_to_update": sum(1 for m in self.meds if m.action == "update"),
            "medicines_unchanged": sum(1 for m in meds_file if m.action == "unchanged"),
            "batches_to_create": sum(1 for b in self.batches if b.action == "create"),
            "batches_skipped": sum(1 for b in self.batches if b.action == "skip"),
            "units_to_add": sum(b.units for b in self.batches if b.action == "create"),
            "errors": len(self.errors), "warnings": len(self.warnings),
        }


def _label(generic, brand, strength, form):
    return f"{generic}{' - ' + brand if brand else ''} {strength} {form}".strip()


def _same(a, b):
    if a is None and b is None:
        return True
    num = (int, float)
    if isinstance(a, num) and isinstance(b, num) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(a - b) < 1e-9
    if isinstance(a, str) or isinstance(b, str):
        return (a or "") == (b or "")
    return a == b


def _diff(obj, wanted: dict):
    return {f: v for f, v in wanted.items() if not _same(getattr(obj, f), v)}


# ---------- payload (what the server keeps between preview and confirm) ----------

def payload_from_parse(result: MedicineParseResult) -> str:
    return json.dumps({"medicines": [m.to_dict() for m in result.medicines],
                       "stock": [s.to_dict() for s in result.stock]})


def parse_from_payload(payload: str) -> MedicineParseResult:
    data = json.loads(payload)
    r = MedicineParseResult()
    r.medicines = [MedRow(**m) for m in data["medicines"]]
    for s in data["stock"]:
        s = dict(s)
        s["expiry"] = date.fromisoformat(s["expiry"]) if s.get("expiry") else None
        s["received"] = date.fromisoformat(s["received"]) if s.get("received") else None
        r.stock.append(StockRow(**s))
    return r


# ---------- PLAN ----------

def plan_medicine_import(db: Session, hospital_id: int, actor_role: str, parsed: MedicineParseResult) -> Plan:
    plan = Plan()
    can_change_schedule = actor_role in SCHEDULE_CHANGERS

    existing = db.query(HospitalMedicine).filter(HospitalMedicine.hospital_id == hospital_id).all()
    generic_map, kids, child_map = {}, {}, {}
    for m in existing:
        if m.parent_medicine_id is None:
            k = (norm_key(m.generic_name), norm_strength_key(m.strength), norm_key(m.dosage_forms))
            cur = generic_map.get(k)
            if cur is None or (not cur.is_active and m.is_active):
                generic_map[k] = m
    for m in existing:
        if m.parent_medicine_id is not None:
            kids.setdefault(m.parent_medicine_id, []).append(m)
            child_map[(m.parent_medicine_id, norm_key(m.brand_name))] = m

    groups = {}
    for r in parsed.medicines:
        groups.setdefault(r.group_key, []).append(r)

    planned = {}   # full_key -> PlannedMed

    for gkey, rows in groups.items():
        first = rows[0]
        generic_row = next((r for r in rows if not r.brand), None)
        brand_rows = [r for r in rows if r.brand]
        hsn = next((r.hsn for r in rows if r.hsn), "")
        nppa = next((r.nppa for r in rows if r.nppa is not None), None)
        category = next((r.category for r in rows if r.category), "")
        parent = generic_map.get(gkey)
        parent_full = gkey + ("",)

        if parent is not None:
            if parent.pack_size != first.pack_size:
                plan.errors.append(Issue("Medicines", first.row, "Units per pack",
                    f"{_label(first.generic, '', first.strength, first.form)} already exists with {parent.pack_size} units per pack "
                    f"(your file says {first.pack_size}). Changing pack size would change what stock means, so fix the file or change it on the medicine screen."))
                continue
            if parent.billing_mode != first.billing_mode:
                plan.warnings.append(Issue("Medicines", first.row, "Billing mode",
                    "Billing mode differs from the existing medicine. The existing billing mode is kept."))
            group_wanted = {"gst_percent": first.gst, "schedule": first.schedule}
            if hsn:
                group_wanted["hsn_code"] = hsn
            if nppa is not None:
                group_wanted["nppa_ceiling_price"] = nppa
            group_changes = _diff(parent, group_wanted)
            if "schedule" in group_changes and not can_change_schedule:
                plan.errors.append(Issue("Medicines", first.row, "Schedule",
                    f"{_label(first.generic, '', first.strength, first.form)} already exists with schedule "
                    f"{(parent.schedule or 'otc').upper()}. Only an admin can change a medicine's schedule. "
                    f"Ask your hospital admin to import this file, or correct the Schedule in the file."))
                continue
            parent_changes = dict(group_changes)
            if category and not _same(parent.category, category):
                parent_changes["category"] = category
            if generic_row:
                parent_changes.update(_diff(parent, {
                    "price_per_pack": generic_row.price_per_pack, "low_stock_threshold": generic_row.threshold,
                    "is_active": generic_row.active}))
                if "price_per_pack" in parent_changes:
                    parent_changes["price"] = compute_unit_price(generic_row.price_per_pack, parent.pack_size)
            pm = PlannedMed(parent_full, (generic_row or first).row, True, "update" if parent_changes else "unchanged",
                            _label(parent.generic_name, "", parent.strength or "", parent.dosage_forms or ""),
                            existing=parent, changes=parent_changes, in_file=generic_row is not None)
            planned[parent_full] = pm

            # children: cascade group-level changes (as update_medicine does) + the file's own brand rows
            in_file_brands = {norm_key(r.brand): r for r in brand_rows}
            for child in kids.get(parent.id, []):
                bkey = norm_key(child.brand_name)
                fr = in_file_brands.pop(bkey, None)
                if fr is None and not child.is_active:
                    continue
                ch = {f: v for f, v in group_changes.items() if f in _CASCADE and not _same(getattr(child, f), v)}
                if fr is not None:
                    ch.update(_diff(child, {"price_per_pack": fr.price_per_pack, "low_stock_threshold": fr.threshold,
                                            "is_active": fr.active}))
                    if "price_per_pack" in ch:
                        ch["price"] = compute_unit_price(fr.price_per_pack, child.pack_size)
                if fr is None and not ch:
                    continue
                planned[gkey + (bkey,)] = PlannedMed(
                    gkey + (bkey,), (fr or first).row, False, "update" if ch else "unchanged",
                    _label(child.generic_name, child.brand_name or "", child.strength or "", child.dosage_forms or ""),
                    existing=child, parent_key=parent_full, changes=ch, in_file=fr is not None)
            for bkey, fr in in_file_brands.items():     # brand not in catalog yet -> create under the existing parent
                if parent.brand_names and any(b.strip().casefold() == bkey for b in parent.brand_names.split(",")):
                    plan.warnings.append(Issue("Medicines", fr.row, "Brand name",
                        f"'{fr.brand}' is already listed as text on the existing generic row. A separate brand row will be created, as the 'Add brand' screen does."))
                planned[gkey + (bkey,)] = _new_brand(gkey, fr, parent_full, parent=parent,
                                                     group=(hsn, nppa, category))
        else:
            vals_parent = {
                "generic_name": first.generic, "brand_names": "", "category": category, "dosage_forms": first.form,
                "strength": first.strength, "schedule": first.schedule,
                "low_stock_threshold": generic_row.threshold if generic_row else first.threshold,
                "pack_size": first.pack_size, "price_per_pack": generic_row.price_per_pack if generic_row else None,
                "nppa_ceiling_price": nppa, "billing_mode": first.billing_mode, "gst_percent": first.gst,
                "hsn_code": hsn or None,
                "price": compute_unit_price(generic_row.price_per_pack, first.pack_size) if generic_row else None,
                "stock_quantity": 0, "is_active": generic_row.active if generic_row else True,
            }
            planned[parent_full] = PlannedMed(parent_full, (generic_row or first).row, True, "create",
                                              _label(first.generic, "", first.strength, first.form),
                                              values=vals_parent, in_file=True)
            for fr in brand_rows:
                planned[fr.full_key] = _new_brand(gkey, fr, parent_full, parent=None, group=(hsn, nppa, category),
                                                  parent_vals=vals_parent)

    plan.meds = sorted(planned.values(), key=lambda p: (p.row, not p.is_parent))

    # ---------- stock ----------
    by_key = {p.key: p for p in plan.meds}
    db_ids = [p.existing.id for p in plan.meds if p.existing is not None]
    stock_targets = {}   # full_key -> (PlannedMed or None, HospitalMedicine or None)
    for s in parsed.stock:
        if s.full_key in stock_targets:
            continue
        pm = by_key.get(s.full_key)
        obj = pm.existing if pm else None
        if pm is None:
            gk = s.full_key[:3]
            if not s.brand:
                obj = generic_map.get(gk)
            else:
                par = generic_map.get(gk)
                obj = child_map.get((par.id, norm_key(s.brand))) if par else None
        stock_targets[s.full_key] = (pm, obj)
        if obj is not None:
            db_ids.append(obj.id)
    have = set()
    if db_ids:
        for mid, bn in db.query(MedicineBatch.medicine_id, MedicineBatch.batch_number).filter(
                MedicineBatch.hospital_id == hospital_id, MedicineBatch.medicine_id.in_(db_ids)).all():
            have.add((mid, (bn or "").strip().casefold()))

    for s in parsed.stock:
        pm, obj = stock_targets[s.full_key]
        label = _label(s.generic, s.brand, s.strength, s.form)
        if pm is None and obj is None:
            plan.errors.append(Issue("Stock", s.row, "Generic name",
                f"{label} is not in the Medicines sheet and not in your catalog. Add it to the Medicines sheet (with the same brand, strength and form)."))
            continue
        if pm is not None and pm.is_parent and pm.existing is None and pm.values.get("price_per_pack") is None and not s.brand:
            plan.errors.append(Issue("Stock", s.row, "Brand name",
                f"{label}: only brand rows exist in the Medicines sheet for this medicine. Write the brand name, or add a Medicines row with no brand."))
            continue
        pack = obj.pack_size if obj is not None else pm.values["pack_size"]
        units = s.quantity_units
        if units is None:
            u = s.qty_packs * pack
            if abs(u - round(u)) > 1e-9:
                plan.errors.append(Issue("Stock", s.row, "Quantity in packs",
                    f"{s.qty_packs:g} packs x {pack} units per pack is not a whole number of units"))
                continue
            units = int(round(u))
            if units > MAX_BATCH_UNITS:
                plan.errors.append(Issue("Stock", s.row, "Quantity in packs", f"Quantity is too large (maximum {MAX_BATCH_UNITS:,} units in one batch)"))
                continue
        if obj is not None and (obj.id, s.batch.strip().casefold()) in have:
            plan.batches.append(PlannedBatch(s.row, s.full_key, "skip", s.batch, units, s.expiry, s.received, s.expired))
            plan.warnings.append(Issue("Stock", s.row, "Batch number",
                f"Batch '{s.batch}' already exists for {label}. Skipped (stock is never counted twice)."))
            continue
        plan.batches.append(PlannedBatch(s.row, s.full_key, "create", s.batch, units, s.expiry, s.received, s.expired))
    plan.stock_targets = stock_targets
    return plan


def _new_brand(gkey, fr: MedRow, parent_full, parent, group, parent_vals=None):
    hsn, nppa, category = group
    src = parent_vals or {}
    vals = {
        "generic_name": parent.generic_name if parent else src["generic_name"],
        "category": (parent.category if parent else src["category"]),
        "dosage_forms": parent.dosage_forms if parent else src["dosage_forms"],
        "strength": (parent.strength if parent else src["strength"]),
        "schedule": parent.schedule if parent else src["schedule"],
        "brand_name": fr.brand, "low_stock_threshold": fr.threshold,
        "pack_size": parent.pack_size if parent else src["pack_size"],
        "price_per_pack": fr.price_per_pack,
        "billing_mode": parent.billing_mode if parent else src["billing_mode"],
        "gst_percent": parent.gst_percent if parent else src["gst_percent"],
        "hsn_code": (parent.hsn_code if parent and parent.hsn_code else (hsn or None)),
        "nppa_ceiling_price": (parent.nppa_ceiling_price if parent and parent.nppa_ceiling_price is not None else nppa),
        "price": compute_unit_price(fr.price_per_pack, parent.pack_size if parent else src["pack_size"]),
        "stock_quantity": 0, "is_active": fr.active,
    }
    return PlannedMed(fr.full_key, fr.row, False, "create", _label(fr.generic, fr.brand, fr.strength, fr.form),
                      parent_key=parent_full, values=vals)


def plan_to_dict(plan: Plan, preview_limit: int = 50):
    meds = []
    for p in plan.meds:
        if not p.in_file and p.action != "update":
            continue
        meds.append({"row": p.row, "action": p.action, "label": p.label,
                     "changes": [f"{f} -> {v}" for f, v in p.changes.items()] if p.action == "update" else []})
    stock = [{"row": b.row, "action": b.action, "batch": b.batch, "units": b.units,
              "expiry": b.expiry.isoformat() if b.expiry else None, "expired": b.expired} for b in plan.batches]
    return {"counts": plan.counts(), "medicines_preview": meds[:preview_limit], "stock_preview": stock[:preview_limit]}


# ---------- preview store ----------

def save_preview(db: Session, doctor, hospital_id: int, file_name: str, parsed: MedicineParseResult) -> str:
    import secrets
    now = now_ist_naive()
    db.query(ImportPreview).filter(ImportPreview.expires_at < now).delete(synchronize_session=False)
    pid = secrets.token_urlsafe(24)
    db.add(ImportPreview(id=pid, hospital_id=hospital_id, doctor_id=doctor.id, kind=KIND,
                         file_name=(file_name or "")[:200], payload=payload_from_parse(parsed),
                         created_at=now, expires_at=now + timedelta(minutes=PREVIEW_MINUTES)))
    db.commit()
    return pid


# ---------- APPLY ----------

def _snapshot(obj, fields):
    return {f: getattr(obj, f) for f in fields}


def apply_plan(db: Session, plan: Plan, actor, hospital_id: int, file_name: str) -> ImportBatch:
    """Writes everything in ONE transaction. The caller commits nothing else in between; any failure -> rollback."""
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

    objs = {}   # full_key -> HospitalMedicine
    ordered = sorted(plan.meds, key=lambda p: (not p.is_parent, p.row))
    for p in ordered:
        if p.action == "create":
            vals = dict(p.values)
            if not p.is_parent:
                vals["parent_medicine_id"] = objs[p.parent_key].id
            m = HospitalMedicine(hospital_id=hospital_id, **vals)
            db.add(m)
            db.flush()
            objs[p.key] = m
            item("medicine", m.id, "created")
        else:
            m = p.existing
            objs[p.key] = m
            if p.action == "update":
                before = _snapshot(m, p.changes.keys())
                for f, v in p.changes.items():
                    setattr(m, f, v)
                item("medicine", m.id, "updated", before, _snapshot(m, p.changes.keys()))

    for b in plan.batches:
        if b.action != "create":
            continue
        pm, obj = plan.stock_targets[b.med_key]
        med = objs.get(b.med_key) or obj
        row = MedicineBatch(medicine_id=med.id, hospital_id=hospital_id, batch_number=b.batch,
                            quantity=b.units, expiry_date=b.expiry, received_date=b.received or ist_today())
        db.add(row)
        db.flush()
        med.stock_quantity = (med.stock_quantity or 0) + b.units
        item("medicine_batch", row.id, "created", None, {"quantity": b.units, "medicine_id": med.id})

    stage_action(db, actor, "medicine_import_applied", "import_batch", batch.id, file_name,
                 details=", ".join(f"{k}={v}" for k, v in counts.items()), hospital_id=hospital_id)
    db.commit()
    return batch


# ---------- UNDO ----------

def _current_matches(obj, after: dict):
    return all(_same(getattr(obj, f), v) for f, v in after.items())


def undo_import(db: Session, batch: ImportBatch, actor) -> dict:
    if batch.status != "applied":
        raise ImportRefused("This import was already undone.")
    latest = db.query(ImportBatch).filter(ImportBatch.hospital_id == batch.hospital_id, ImportBatch.kind == batch.kind,
                                          ImportBatch.status == "applied").order_by(ImportBatch.id.desc()).first()
    if latest is None or latest.id != batch.id:
        raise ImportRefused("Only the most recent import can be undone. Undo the newer import first.")

    items = db.query(ImportBatchItem).filter(ImportBatchItem.batch_id == batch.id).all()
    created_batch_ids = {i.entity_id for i in items if i.entity == "medicine_batch" and i.action == "created"}
    created_med_ids = {i.entity_id for i in items if i.entity == "medicine" and i.action == "created"}
    problems = []

    batches = {}
    for i in items:
        if i.entity == "medicine_batch":
            b = db.query(MedicineBatch).filter(MedicineBatch.id == i.entity_id).first()
            after = json.loads(i.after_json or "{}")
            if b is None:
                problems.append("A batch from this import no longer exists.")
                continue
            batches[b.id] = (b, after)
            if b.quantity != after.get("quantity"):
                problems.append(f"Batch {b.batch_number or '-'} has been sold, adjusted or written off since the import.")
            if db.query(MedicineOrderBatch.id).filter(MedicineOrderBatch.batch_id == b.id).first():
                problems.append(f"Batch {b.batch_number or '-'} has already been dispensed.")
    meds = {}
    for i in items:
        if i.entity != "medicine":
            continue
        m = db.query(HospitalMedicine).filter(HospitalMedicine.id == i.entity_id).first()
        if m is None:
            problems.append("A medicine from this import no longer exists.")
            continue
        meds[m.id] = (m, i)
        if i.action == "created":
            name = m.generic_name + (f" - {m.brand_name}" if m.brand_name else "")
            if db.query(MedicineOrder.id).filter(MedicineOrder.catalog_medicine_id == m.id).first() or \
               db.query(AdmissionMedicationOrder.id).filter(AdmissionMedicationOrder.medicine_id == m.id).first():
                problems.append(f"{name} has already been used in an order.")
            other_batches = db.query(MedicineBatch.id).filter(MedicineBatch.medicine_id == m.id).all()
            if any(bid not in created_batch_ids for (bid,) in other_batches):
                problems.append(f"{name} has stock that was added after the import.")
            if db.query(HospitalMedicine.id).filter(HospitalMedicine.parent_medicine_id == m.id,
                                                    ~HospitalMedicine.id.in_(created_med_ids or [0])).first():
                problems.append(f"{name} has brands that were added after the import.")
        else:
            if not _current_matches(m, json.loads(i.after_json or "{}")):
                problems.append(f"{m.generic_name} was edited after the import, so its old values cannot be restored safely.")
    if problems:
        uniq = list(dict.fromkeys(problems))
        raise ImportRefused("This import cannot be undone because some of it is already in use. Nothing was changed.", uniq[:10])

    for b, after in batches.values():
        med = db.query(HospitalMedicine).filter(HospitalMedicine.id == b.medicine_id).first()
        if med is not None:
            med.stock_quantity = max(0, (med.stock_quantity or 0) - b.quantity)
        db.delete(b)
    db.flush()
    for m, i in meds.values():
        if i.action == "updated":
            for f, v in json.loads(i.before_json or "{}").items():
                setattr(m, f, v)
    created = [m for m, i in meds.values() if i.action == "created"]
    for m in sorted(created, key=lambda x: x.parent_medicine_id is None):   # brand rows first, then generic rows
        db.delete(m)
        db.flush()
    batch.status = "undone"
    batch.undone_at = now_ist_naive()
    batch.undone_by = actor.id
    restored = sum(1 for m, i in meds.values() if i.action == "updated")
    stage_action(db, actor, "medicine_import_undone", "import_batch", batch.id, batch.file_name,
                 details=f"batches_removed={len(batches)}, medicines_removed={len(created)}, medicines_restored={restored}",
                 hospital_id=batch.hospital_id)
    db.commit()
    return {"batches_removed": len(batches), "medicines_removed": len(created), "medicines_restored": restored}