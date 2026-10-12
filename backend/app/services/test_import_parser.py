"""Reads and checks the lab tests Excel file (ONE sheet "Tests"). No database, no saving.
Mirrors the Add Test screen: a main row is a test; with Has parameters = Y it is a PANEL and its
parameter rows (rows with a Parent test) become parameter rows under it."""
import io
from dataclasses import dataclass, field, asdict
from typing import Optional

from app.services.import_common import (
    ImportFileError, Issue, read_table, norm_text, norm_key, parse_number, parse_whole, parse_yn, is_blank,
)

MAX_TEST_ROWS = 3000
MAX_PARAMS_PER_PANEL = 200
MAX_PRICE = 1_000_000          # same bound as _check_test_payload in routers/tests.py

# (key, header text in the template, required header)
TEST_COLUMNS = [
    ("name", "Test name*", True),
    ("parent", "Parent test", False),
    ("has_params", "Has parameters*", True),
    ("category", "Category", False),
    ("price", "Price*", True),
    ("tube", "Sample tube", False),
    ("fasting", "Fasting required", False),
    ("tat", "Turnaround hours", False),
    ("aliases", "Other names", False),
    ("unit", "Unit", False),
    ("mlow", "Male low", False),
    ("mhigh", "Male high", False),
    ("flow", "Female low", False),
    ("fhigh", "Female high", False),
    ("reftext", "Reference text", False),
    ("clow", "Critical low", False),
    ("chigh", "Critical high", False),
    ("order", "Order", False),
    ("purpose", "Purpose", False),
    ("irreplaceable", "Irreplaceable sample", False),
    ("nabl", "NABL accredited", False),
    ("active", "Active", False),
]
_LABEL = {k: l.rstrip("*") for k, l, _ in TEST_COLUMNS}
_RANGE_KEYS = ("mlow", "mhigh", "flow", "fhigh", "reftext")


@dataclass
class ParamRow:
    row: int
    name: str
    unit: str
    ref_male: str
    ref_female: str
    crit_low: Optional[float]
    crit_high: Optional[float]
    order: int
    purpose: str = ""


@dataclass
class TestRow:
    row: int
    name: str
    is_panel: bool
    category: str
    price: float
    tube: str
    fasting: Optional[bool]       # None = left blank
    tat: Optional[int]
    aliases: str
    unit: str
    ref_male: str
    ref_female: str
    crit_low: Optional[float]
    crit_high: Optional[float]
    params: list = field(default_factory=list)
    purpose: str = ""
    irreplaceable: Optional[bool] = None   # None = left blank
    nabl: Optional[bool] = None
    active: Optional[bool] = None

    @property
    def key(self):
        return norm_key(self.name)


@dataclass
class TestParseResult:
    tests: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    rows_read: int = 0

    @property
    def ok(self):
        return not self.errors

    def to_dict(self, preview_limit: int = 50):
        return {
            "ok": self.ok,
            "counts": {"rows": self.rows_read, "tests": len(self.tests),
                       "panels": sum(1 for t in self.tests if t.is_panel),
                       "parameters": sum(len(t.params) for t in self.tests),
                       "errors": len(self.errors), "warnings": len(self.warnings)},
            "errors": [i.to_dict() for i in self.errors],
            "warnings": [i.to_dict() for i in self.warnings],
            "tests_preview": [{"row": t.row, "name": t.name, "panel": t.is_panel, "price": t.price,
                               "parameters": len(t.params)} for t in self.tests[:preview_limit]],
        }


def tests_to_payload(tests) -> list:
    return [asdict(t) for t in tests]


def tests_from_payload(items) -> list:
    out = []
    for d in items:
        d = dict(d)
        params = [ParamRow(**p) for p in d.pop("params", [])]
        out.append(TestRow(params=params, **d))
    return out


def _fmt(x: float) -> str:
    s = ("%.6f" % x).rstrip("0").rstrip(".")
    return s or "0"


def range_text(low, high) -> str:
    """Plain low-high text. The model listener turns it back into numbers (13-17, <5, >2.5)."""
    if low is not None and high is not None:
        return f"{_fmt(low)}-{_fmt(high)}"
    if high is not None:
        return f"<{_fmt(high)}"
    if low is not None:
        return f">{_fmt(low)}"
    return ""


def _text(v, maxlen, err, col):
    s = norm_text(v)
    if len(s) > maxlen:
        err(col, f"{col} is too long (maximum {maxlen} characters)")
        return s[:maxlen]
    return s


def _parse_values(v, err):
    """Unit, ranges, reference text, critical values, order: shared by main (single) and parameter rows."""
    unit = _text(v["unit"], 50, err, "Unit")
    nums = {}
    for key, label in (("mlow", "Male low"), ("mhigh", "Male high"), ("flow", "Female low"), ("fhigh", "Female high")):
        n, e = parse_number(v[key])
        if e:
            err(label, f"{label}: {e}")
            n = None
        elif n is not None and n < 0:
            err(label, f"{label}: negative limits are not supported. Use Reference text for ranges like -2 to 2")
            n = None
        nums[key] = n
    for lo, hi, label in (("mlow", "mhigh", "Male"), ("flow", "fhigh", "Female")):
        if nums[lo] is not None and nums[hi] is not None and nums[lo] >= nums[hi]:
            err(f"{label} low", f"{label} low must be less than {label.lower()} high")
    reftext = _text(v["reftext"], 200, err, "Reference text")
    male = range_text(nums["mlow"], nums["mhigh"])
    female = range_text(nums["flow"], nums["fhigh"])
    ref_male = male or reftext
    ref_female = female or reftext
    clow, e = parse_number(v["clow"])
    if e:
        err("Critical low", f"Critical low: {e}")
        clow = None
    chigh, e = parse_number(v["chigh"])
    if e:
        err("Critical high", f"Critical high: {e}")
        chigh = None
    if clow is not None and chigh is not None and clow >= chigh:
        err("Critical low", "Critical low must be less than critical high")
    order, e = parse_whole(v["order"])
    if e:
        err("Order", f"Order: {e}")
        order = None
    elif order is not None and order < 0:
        err("Order", "Order must be 0 or more")
        order = None
    used_text_and_numbers = bool(reftext and (male or female))
    return unit, ref_male, ref_female, clow, chigh, order, used_text_and_numbers


def _filled(v, keys):
    return [_LABEL[k] for k in keys if not is_blank(v[k])]


def parse_tests_workbook(content: bytes) -> TestParseResult:
    import openpyxl
    result = TestParseResult()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception:
        raise ImportFileError("Could not read this file. Make sure it is a valid, unprotected .xlsx.")
    try:
        rows = read_table(wb, "Tests", TEST_COLUMNS, MAX_TEST_ROWS, result.errors, True)
    finally:
        wb.close()
    result.rows_read = len(rows or [])
    if rows is None:
        return result
    if not rows:
        result.errors.append(Issue("Tests", None, None, "The Tests sheet has no rows."))
        return result

    def mk(n):
        def err(col, msg):
            result.errors.append(Issue("Tests", n, col, msg))

        def warn(col, msg):
            result.warnings.append(Issue("Tests", n, col, msg))
        return err, warn

    mains, bad_keys, first_row = {}, set(), {}
    children = []
    for n, v in rows:
        err, warn = mk(n)
        name = norm_text(v["name"])
        parent = norm_text(v["parent"])
        if not name:
            err("Test name", "Test name is missing")
            continue
        if len(name) > 150:
            err("Test name", "Test name is too long (maximum 150 characters)")
            continue
        if parent:
            children.append((n, v, name, parent))
            continue
        key = norm_key(name)
        if key in first_row:
            err("Test name", f"Duplicate test name (also on row {first_row[key]}). Each main test must appear once.")
            bad_keys.add(key)
            continue
        first_row[key] = n
        before = len(result.errors)

        hp, e = parse_yn(v["has_params"], None)
        if e:
            err("Has parameters", f"Has parameters: {e}")
        elif hp is None:
            err("Has parameters", "Has parameters is missing (write Y or N)")
        price, e = parse_number(v["price"])
        if e:
            err("Price", f"Price: {e}")
        elif price is None:
            err("Price", "Price is missing")
        elif not (0 <= price <= MAX_PRICE):
            err("Price", f"Price must be between 0 and {MAX_PRICE:,}")
        category = _text(v["category"], 100, err, "Category")
        tube = _text(v["tube"], 100, err, "Sample tube")
        fasting, e = parse_yn(v["fasting"], None)
        if e:
            err("Fasting required", f"Fasting required: {e}")
        tat, e = parse_whole(v["tat"])
        if e:
            err("Turnaround hours", f"Turnaround hours: {e}")
        elif tat is not None and not (1 <= tat <= 10000):
            err("Turnaround hours", "Turnaround hours must be between 1 and 10,000")
            tat = None
        aliases = ", ".join(a for a in (norm_text(x) for x in norm_text(v["aliases"]).split(",")) if a)
        if len(aliases) > 500:
            err("Other names", "Other names is too long (maximum 500 characters)")

        unit, rm, rf, clow, chigh, order, mixed = _parse_values(v, err)
        purpose = _text(v["purpose"], 1000, err, "Purpose")
        irreplaceable, e = parse_yn(v["irreplaceable"], None)
        if e:
            err("Irreplaceable sample", f"Irreplaceable sample: {e}")
        nabl, e = parse_yn(v["nabl"], None)
        if e:
            err("NABL accredited", f"NABL accredited: {e}")
        active, e = parse_yn(v["active"], None)
        if e:
            err("Active", f"Active: {e}")
        if hp:   # panel: its own unit / ranges / criticals live on the parameters
            ignored = _filled(v, ("unit",) + _RANGE_KEYS + ("clow", "chigh", "order"))
            if ignored:
                warn(ignored[0], f"This test has parameters, so these cells are ignored on the main row: {', '.join(ignored)}. Put them on the parameter rows.")
            unit, rm, rf, clow, chigh = "", "", "", None, None
        else:
            if not is_blank(v["order"]):
                warn("Order", "Order is ignored on a test without parameters.")
            if mixed:
                warn("Reference text", "Reference text is used only where Low/High are blank; the Low/High numbers win.")
        if len(result.errors) > before:
            bad_keys.add(key)
            continue
        mains[key] = TestRow(row=n, name=name, is_panel=bool(hp), category=category, price=price, tube=tube,
                             fasting=fasting, tat=tat, aliases=aliases, unit=unit, ref_male=rm, ref_female=rf,
                             crit_low=clow, crit_high=chigh, purpose=purpose, irreplaceable=irreplaceable,
                             nabl=nabl, active=active)

    # ---- parameter rows ----
    n_children = {}
    seen_params = {}
    for n, v, name, parent in children:
        err, warn = mk(n)
        pkey = norm_key(parent)
        if pkey in bad_keys:
            continue                      # the main row already has an error
        main = mains.get(pkey)
        if main is None:
            err("Parent test", f"Parent test '{parent[:40]}' was not found. It must be written exactly like a main test's name (a row with an empty Parent test).")
            continue
        before = len(result.errors)
        unit, rm, rf, clow, chigh, order, mixed = _parse_values(v, err)
        purpose = _text(v["purpose"], 1000, err, "Purpose")
        ignored = _filled(v, ("category", "price", "tube", "fasting", "tat", "aliases", "has_params", "irreplaceable", "nabl", "active"))
        if ignored:
            warn(ignored[0], f"These cells are ignored on a parameter row: {', '.join(ignored)}.")
        if mixed:
            warn("Reference text", "Reference text is used only where Low/High are blank; the Low/High numbers win.")
        if len(result.errors) > before:
            continue
        p = ParamRow(row=n, name=name, unit=unit, ref_male=rm, ref_female=rf, crit_low=clow, crit_high=chigh,
                     order=order if order is not None else -1, purpose=purpose)
        if not main.is_panel:
            n_children.setdefault(pkey, []).append(p)
            continue
        dk = (pkey, norm_key(name))
        if dk in seen_params:
            err("Test name", f"Parameter '{name}' is listed twice under {main.name} (first on row {seen_params[dk]}). Results are stored by parameter name, so each name can appear once per panel.")
            continue
        seen_params[dk] = n
        main.params.append(p)

    # single tests: one child row with the same name and compatible values is silently ignored
    for pkey, plist in n_children.items():
        main = mains[pkey]
        if len(plist) == 1 and norm_key(plist[0].name) == pkey:
            p = plist[0]
            same = (p.unit in ("", main.unit) and p.ref_male in ("", main.ref_male) and p.ref_female in ("", main.ref_female)
                    and p.crit_low in (None, main.crit_low) and p.crit_high in (None, main.crit_high))
            if same:
                continue
        for p in plist:
            result.errors.append(Issue("Tests", p.row, "Parent test",
                f"'{main.name}' says it has no parameters (Has parameters = N) but this row is a parameter of it. "
                f"Set Has parameters to Y on the main row, or delete this row."))

    final = []
    for t in sorted(mains.values(), key=lambda x: x.row):
        if t.is_panel:
            if not t.params:
                result.errors.append(Issue("Tests", t.row, "Has parameters",
                    f"'{t.name}' has Has parameters = Y but no parameter rows. Add rows with Parent test = {t.name}, or set it to N."))
                continue
            if len(t.params) > MAX_PARAMS_PER_PANEL:
                result.errors.append(Issue("Tests", t.row, "Has parameters", f"Too many parameters (maximum {MAX_PARAMS_PER_PANEL} per panel)."))
                continue
            ordered = sorted(t.params, key=lambda x: x.row)
            for i, p in enumerate(ordered):
                if p.order < 0:
                    p.order = i
            t.params = sorted(ordered, key=lambda x: (x.order, x.row))
        final.append(t)
    result.tests = final
    return result