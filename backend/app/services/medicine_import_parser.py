"""Reads and checks the medicines Excel file. NO database and NO saving in this file:
it only turns the sheet into clean rows plus a list of errors and warnings."""
import io
from dataclasses import dataclass, field
from typing import Optional

from app.routers.medicines import (
    VALID_SCHEDULES, VALID_BILLING_MODES, MAX_PRICE, MAX_GST_PERCENT,
    MAX_PACK_SIZE, MAX_THRESHOLD, compute_unit_price,
)
from app.utils.auth import ist_today
from app.services.import_common import (
    ImportFileError, Issue, read_table, norm_text, norm_key, norm_strength_key,
    parse_number, parse_whole, parse_date, parse_yn, is_blank,
)

MAX_MEDICINE_ROWS = 2000
MAX_STOCK_ROWS = 5000
MAX_BATCH_UNITS = 10_000_000   # same limit as BatchIn.quantity in routers/medicines.py

# Same list as the Dosage Form dropdown on the medicines page (+ "Other").
FORMS = ["Tablet", "Capsule", "Sachet", "Suppository", "Patch", "Syrup", "Suspension", "Injection",
         "Drops", "Ointment", "Cream", "Gel", "Lotion", "Inhaler", "Spray", "Powder", "Other"]
GST_CHOICES = [0, 5, 12, 18, 28]
SCHEDULE_CHOICES = ["OTC", "H", "H1", "X"]
BILLING_CHOICES = ["Per pack", "Per unit"]
YN_CHOICES = ["Y", "N"]

# (key, header text in the template, required)
MED_COLUMNS = [
    ("generic", "Generic name*", True),
    ("brand", "Brand name", False),
    ("strength", "Strength*", True),
    ("form", "Form*", True),
    ("pack", "Units per pack*", True),
    ("billing", "Billing mode*", True),
    ("price", "MRP per pack*", True),
    ("gst", "GST %*", True),
    ("schedule", "Schedule*", True),
    ("hsn", "HSN code", False),
    ("nppa", "NPPA ceiling price per unit", False),
    ("threshold", "Low-stock alert at", False),
    ("category", "Category", False),
    ("active", "Active", False),
]
STOCK_COLUMNS = [
    ("generic", "Generic name*", True),
    ("brand", "Brand name", False),
    ("strength", "Strength*", True),
    ("form", "Form*", True),
    ("batch", "Batch number*", True),
    ("expiry", "Expiry date*", True),
    ("qty", "Quantity in packs*", True),
    ("received", "Received date", False),
]

_FORM_LOOKUP = {f.casefold(): f for f in FORMS}


@dataclass
class MedRow:
    row: int
    generic: str
    brand: str
    strength: str
    form: str
    pack_size: int
    billing_mode: str            # per_pack / per_unit
    price_per_pack: float
    gst: float
    schedule: str                # otc / h / h1 / x
    hsn: str
    nppa: Optional[float]
    threshold: int
    category: str
    active: bool

    @property
    def group_key(self):         # one generic (parent) row in the catalog
        return (norm_key(self.generic), norm_strength_key(self.strength), norm_key(self.form))

    @property
    def full_key(self):          # one sellable product
        return self.group_key + (norm_key(self.brand),)

    def to_dict(self):
        return {"row": self.row, "generic": self.generic, "brand": self.brand, "strength": self.strength,
                "form": self.form, "pack_size": self.pack_size, "billing_mode": self.billing_mode,
                "price_per_pack": self.price_per_pack, "gst": self.gst, "schedule": self.schedule,
                "hsn": self.hsn, "nppa": self.nppa, "threshold": self.threshold,
                "category": self.category, "active": self.active}


@dataclass
class StockRow:
    row: int
    generic: str
    brand: str
    strength: str
    form: str
    batch: str
    expiry: object
    qty_packs: float
    received: object
    quantity_units: Optional[int]    # filled when the medicine is in this same file
    linked_in_file: bool
    expired: bool

    @property
    def full_key(self):
        return (norm_key(self.generic), norm_strength_key(self.strength), norm_key(self.form), norm_key(self.brand))

    def to_dict(self):
        return {"row": self.row, "generic": self.generic, "brand": self.brand, "strength": self.strength,
                "form": self.form, "batch": self.batch,
                "expiry": self.expiry.isoformat() if self.expiry else None,
                "qty_packs": self.qty_packs, "quantity_units": self.quantity_units,
                "received": self.received.isoformat() if self.received else None,
                "linked_in_file": self.linked_in_file, "expired": self.expired}


@dataclass
class MedicineParseResult:
    medicines: list = field(default_factory=list)
    stock: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    stock_sheet_found: bool = False
    medicine_rows_read: int = 0
    stock_rows_read: int = 0

    @property
    def ok(self):
        return not self.errors

    def to_dict(self, preview_limit: int = 50):
        groups = {m.group_key for m in self.medicines}
        return {
            "ok": self.ok,
            "counts": {
                "medicine_rows": self.medicine_rows_read,
                "medicine_rows_valid": len(self.medicines),
                "generic_medicines": len(groups),
                "stock_rows": self.stock_rows_read,
                "stock_rows_valid": len(self.stock),
                "stock_rows_linked_in_file": sum(1 for s in self.stock if s.linked_in_file),
                "stock_rows_for_existing_catalog": sum(1 for s in self.stock if not s.linked_in_file),
                "errors": len(self.errors),
                "warnings": len(self.warnings),
            },
            "errors": [i.to_dict() for i in self.errors],
            "warnings": [i.to_dict() for i in self.warnings],
            "medicines_preview": [m.to_dict() for m in self.medicines[:preview_limit]],
            "stock_preview": [s.to_dict() for s in self.stock[:preview_limit]],
        }


def _text(v, maxlen, err, col, required):
    s = norm_text(v)
    if not s:
        if required:
            err(col, f"{col} is missing")
        return ""
    if len(s) > maxlen:
        err(col, f"{col} is too long (maximum {maxlen} characters)")
        return s[:maxlen]
    return s


def _match_form(raw, err):
    s = norm_text(raw)
    if not s:
        err("Form", "Form is missing")
        return ""
    f = _FORM_LOOKUP.get(s.casefold())
    if not f:
        err("Form", f"Form '{s[:30]}' is not in the list. Choose one of: {', '.join(FORMS)}")
        return ""
    return f


def _parse_medicine_row(n, v, result: MedicineParseResult):
    sheet = "Medicines"
    before = len(result.errors)

    def err(col, msg):
        result.errors.append(Issue(sheet, n, col, msg))

    def warn(col, msg):
        result.warnings.append(Issue(sheet, n, col, msg))

    generic = _text(v["generic"], 200, err, "Generic name", True)
    brand = _text(v["brand"], 100, err, "Brand name", False)
    strength = _text(v["strength"], 50, err, "Strength", True)
    form = _match_form(v["form"], err)

    pack, e = parse_whole(v["pack"])
    if e:
        err("Units per pack", f"Units per pack: {e}")
    elif pack is None:
        err("Units per pack", "Units per pack is missing")
    elif not (1 <= pack <= MAX_PACK_SIZE):
        err("Units per pack", f"Units per pack must be between 1 and {MAX_PACK_SIZE:,}")

    billing = None
    braw = norm_key(v["billing"]).replace("_", " ")
    if not braw:
        err("Billing mode", "Billing mode is missing")
    elif braw in ("per pack", "pack"):
        billing = "per_pack"
    elif braw in ("per unit", "unit"):
        billing = "per_unit"
    else:
        err("Billing mode", f"Billing mode '{norm_text(v['billing'])[:20]}' must be Per pack or Per unit")
    if billing and billing not in VALID_BILLING_MODES:
        billing = None

    price, e = parse_number(v["price"])
    if e:
        err("MRP per pack", f"MRP per pack: {e}")
    elif price is None:
        err("MRP per pack", "MRP per pack is missing")
    elif not (0 <= price <= MAX_PRICE):
        err("MRP per pack", f"MRP per pack must be between 0 and {MAX_PRICE:,}")

    gst, e = parse_number(v["gst"])
    if e:
        err("GST %", f"GST %: {e}")
    elif gst is None:
        err("GST %", "GST % is missing")
    elif gst not in GST_CHOICES or not (0 <= gst <= MAX_GST_PERCENT):
        err("GST %", f"GST % must be one of {', '.join(str(g) for g in GST_CHOICES)} (you wrote {norm_text(v['gst'])})")

    schedule = norm_key(v["schedule"])
    if not schedule:
        err("Schedule", "Schedule is missing")
        schedule = None
    elif schedule not in VALID_SCHEDULES:
        err("Schedule", f"Schedule '{norm_text(v['schedule'])[:10]}' must be one of {', '.join(SCHEDULE_CHOICES)}")
        schedule = None

    hsn = _text(v["hsn"], 20, err, "HSN code", False)
    if hsn and not (hsn.isdigit() and 4 <= len(hsn) <= 8):
        warn("HSN code", "HSN code is usually 4 to 8 digits. Please double-check it.")

    nppa, e = parse_number(v["nppa"])
    if e:
        err("NPPA ceiling price per unit", f"NPPA ceiling price: {e}")
    elif nppa is not None and not (0 <= nppa <= MAX_PRICE):
        err("NPPA ceiling price per unit", f"NPPA ceiling price must be between 0 and {MAX_PRICE:,}")

    threshold, e = parse_whole(v["threshold"])
    if e:
        err("Low-stock alert at", f"Low-stock alert at: {e}")
    elif threshold is None:
        threshold = 25   # same default as the Add Medicine screen
    elif not (0 <= threshold <= MAX_THRESHOLD):
        err("Low-stock alert at", f"Low-stock alert at must be between 0 and {MAX_THRESHOLD:,}")

    category = _text(v["category"], 100, err, "Category", False)
    active, e = parse_yn(v["active"], True)
    if e:
        err("Active", f"Active: {e}")

    if len(result.errors) > before:
        return None

    unit_price = compute_unit_price(price, pack)
    if price == 0:
        warn("MRP per pack", "MRP per pack is 0. This medicine would be billed free.")
    if nppa is not None and unit_price is not None and unit_price > nppa:
        warn("NPPA ceiling price per unit",
             f"Price per unit Rs {unit_price:.2f} is above the NPPA ceiling of Rs {nppa:.2f}. Double-check before importing.")

    return MedRow(row=n, generic=generic, brand=brand, strength=strength, form=form, pack_size=pack,
                  billing_mode=billing, price_per_pack=price, gst=gst, schedule=schedule, hsn=hsn,
                  nppa=nppa, threshold=threshold, category=category, active=active)


def _check_medicine_groups(result: MedicineParseResult, valid_rows):
    """Brands of one medicine are stored under one generic row, which owns pack size, billing,
    GST and schedule (the manual 'add brand' screen copies them from the generic). So rows of
    the same generic + strength + form must agree on them."""
    seen = {}
    groups = {}
    for m in valid_rows:
        if m.full_key in seen:
            result.errors.append(Issue("Medicines", m.row, "Generic name",
                f"Duplicate of row {seen[m.full_key]} (same generic name, brand, strength and form). Keep one row."))
            continue
        seen[m.full_key] = m.row
        groups.setdefault(m.group_key, []).append(m)

    kept = []
    for rows in groups.values():
        first = rows[0]
        for m in rows:
            bad = False
            if m is not first:
                for attr, col in (("pack_size", "Units per pack"), ("billing_mode", "Billing mode"),
                                  ("gst", "GST %"), ("schedule", "Schedule")):
                    if getattr(m, attr) != getattr(first, attr):
                        result.errors.append(Issue("Medicines", m.row, col,
                            f"{col} is different from row {first.row}, which is the same medicine "
                            f"(same generic name, strength and form). Brands of one medicine must share it."))
                        bad = True
                for attr, col in (("hsn", "HSN code"), ("nppa", "NPPA ceiling price per unit"), ("category", "Category")):
                    a, b = getattr(m, attr), getattr(first, attr)
                    if a not in ("", None) and b not in ("", None) and a != b:
                        result.warnings.append(Issue("Medicines", m.row, col,
                            f"{col} is different from row {first.row} for the same medicine. The first row's value will be used."))
            if not bad:
                kept.append(m)
    kept.sort(key=lambda r: r.row)
    return kept


def _parse_stock_row(n, v, meds_by_key, today, result: MedicineParseResult):
    sheet = "Stock"
    before = len(result.errors)

    def err(col, msg):
        result.errors.append(Issue(sheet, n, col, msg))

    generic = _text(v["generic"], 200, err, "Generic name", True)
    brand = _text(v["brand"], 100, err, "Brand name", False)
    strength = _text(v["strength"], 50, err, "Strength", True)
    form = _match_form(v["form"], err)
    batch = _text(v["batch"], 50, err, "Batch number", True)

    expiry, e = parse_date(v["expiry"])
    if e:
        err("Expiry date", f"Expiry date: {e}")
    elif expiry is None:
        err("Expiry date", "Expiry date missing")

    received, e = parse_date(v["received"])
    if e:
        err("Received date", f"Received date: {e}")

    qty, e = parse_number(v["qty"])
    if e:
        err("Quantity in packs", f"Quantity in packs: {e}")
    elif qty is None:
        err("Quantity in packs", "Quantity in packs is missing")
    elif qty <= 0:
        err("Quantity in packs", "Quantity in packs must be more than 0")

    if len(result.errors) > before:
        return None

    row = StockRow(row=n, generic=generic, brand=brand, strength=strength, form=form, batch=batch,
                   expiry=expiry, qty_packs=qty, received=received, quantity_units=None,
                   linked_in_file=False, expired=expiry < today)
    med = meds_by_key.get(row.full_key)
    if med:
        units = qty * med.pack_size
        if abs(units - round(units)) > 1e-9:
            err("Quantity in packs", f"{qty:g} packs x {med.pack_size} units per pack is not a whole number of units")
            return None
        units = int(round(units))
        if units > MAX_BATCH_UNITS:
            err("Quantity in packs", f"Quantity is too large (maximum {MAX_BATCH_UNITS:,} units in one batch)")
            return None
        row.quantity_units = units
        row.linked_in_file = True
    if row.expired:
        result.warnings.append(Issue(sheet, n, "Expiry date",
            "This batch is already expired. It will be imported but it can never be sold."))
    return row


def parse_medicines_workbook(content: bytes) -> MedicineParseResult:
    """content = bytes of an .xlsx that already passed check_xlsx_bytes."""
    import openpyxl
    result = MedicineParseResult()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception:
        raise ImportFileError("Could not read this file. Make sure it is a valid, unprotected .xlsx.")
    try:
        med_rows = read_table(wb, "Medicines", MED_COLUMNS, MAX_MEDICINE_ROWS, result.errors, True)
        stock_rows = read_table(wb, "Stock", STOCK_COLUMNS, MAX_STOCK_ROWS, result.errors, False)
    finally:
        wb.close()

    result.stock_sheet_found = stock_rows is not None
    result.medicine_rows_read = len(med_rows or [])
    result.stock_rows_read = len(stock_rows or [])
    if med_rows is not None and not med_rows:
        result.errors.append(Issue("Medicines", None, None, "The Medicines sheet has no rows."))

    parsed = []
    for n, v in med_rows or []:
        m = _parse_medicine_row(n, v, result)
        if m:
            parsed.append(m)
    result.medicines = _check_medicine_groups(result, parsed)

    meds_by_key = {m.full_key: m for m in result.medicines}
    today = ist_today()
    seen_batches = {}
    for n, v in stock_rows or []:
        s = _parse_stock_row(n, v, meds_by_key, today, result)
        if not s:
            continue
        bkey = (s.full_key, s.batch.casefold())
        if bkey in seen_batches:
            result.errors.append(Issue("Stock", n, "Batch number",
                f"Batch '{s.batch}' is listed twice for this medicine (first on row {seen_batches[bkey]})."))
            continue
        seen_batches[bkey] = n
        result.stock.append(s)

    unmatched = sum(1 for s in result.stock if not s.linked_in_file)
    if unmatched:
        result.warnings.append(Issue("Stock", None, None,
            f"{unmatched} stock row(s) are not in the Medicines sheet. At the preview step they will be matched "
            f"against medicines already in your catalog; any that match nothing will be an error."))
    return result