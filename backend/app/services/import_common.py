"""Shared helpers for the Excel import features (medicines now, tests later).
No database access in this file: it only checks files and cleans up cell values."""
import io
import math
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

MAX_IMPORT_BYTES = 5 * 1024 * 1024        # uploaded file size cap
MAX_UNZIPPED_BYTES = 50 * 1024 * 1024     # guards against "zip bombs"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class ImportFileError(Exception):
    """The whole file is unusable (wrong type, too big, missing sheet...)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class Issue:
    sheet: str
    row: Optional[int]
    column: Optional[str]
    message: str

    def to_dict(self):
        where = f"{self.sheet} row {self.row}" if self.row else self.sheet
        return {"sheet": self.sheet, "row": self.row, "column": self.column,
                "message": self.message, "text": f"{where}: {self.message}"}


def check_xlsx_bytes(filename: str, content: bytes) -> None:
    """Accept only a real, macro-free .xlsx. Raises ImportFileError otherwise."""
    name = (filename or "").strip().lower()
    if name.endswith(".xlsm"):
        raise ImportFileError("Macro-enabled files (.xlsm) are not accepted. In Excel choose Save As > Excel Workbook (.xlsx) and upload that.")
    if name.endswith(".xls"):
        raise ImportFileError("Old .xls files are not supported. In Excel choose Save As > Excel Workbook (.xlsx) and upload that.")
    if name.endswith(".csv"):
        raise ImportFileError("CSV files are not supported. Use the downloaded template (.xlsx).")
    if not name.endswith(".xlsx"):
        raise ImportFileError("Only .xlsx Excel files are accepted. Download the template and fill that in.")
    if not content:
        raise ImportFileError("The file is empty.")
    if len(content) > MAX_IMPORT_BYTES:
        raise ImportFileError(f"File is too large (maximum {MAX_IMPORT_BYTES // (1024 * 1024)} MB).", 413)
    not_real = "This is not a real .xlsx file (it may be renamed from another type). Open it in Excel and Save As .xlsx."
    if content[:2] != b"PK" or not zipfile.is_zipfile(io.BytesIO(content)):
        raise ImportFileError(not_real)
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            infos = zf.infolist()
            lowered = {i.filename.lower(): i.filename for i in infos}
            if "xl/workbook.xml" not in lowered or "[content_types].xml" not in lowered:
                raise ImportFileError(not_real)
            if any(n.startswith(("xl/vbaproject", "xl/activex", "xl/embeddings")) for n in lowered):
                raise ImportFileError("This file contains macros or embedded objects, which are not accepted. Save a clean copy as .xlsx.")
            if sum(i.file_size for i in infos) > MAX_UNZIPPED_BYTES:
                raise ImportFileError("File is too large once opened. Split it into smaller files.", 413)
            if b"macroEnabled" in zf.read(lowered["[content_types].xml"]):
                raise ImportFileError("Macro-enabled workbooks are not accepted. Save a clean copy as .xlsx.")
    except zipfile.BadZipFile:
        raise ImportFileError(not_real)


# ---------- cell cleaning ----------

def is_blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def norm_text(v: Any) -> str:
    """Trim, collapse inner spaces, drop control characters. Numbers become plain text (500.0 -> '500')."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Y" if v else "N"
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = _CONTROL_CHARS.sub("", str(v))
    return " ".join(s.split())


def norm_key(v: Any) -> str:
    return norm_text(v).casefold()


def norm_strength_key(v: Any) -> str:
    """'500 mg' and '500mg' must match each other."""
    return re.sub(r"\s+", "", norm_text(v)).casefold()


def header_key(v: Any) -> str:
    return norm_key(v).replace("*", "").strip()


def parse_number(v: Any):
    """Returns (number, None) or (None, 'reason'). Blank -> (None, None)."""
    if is_blank(v):
        return None, None
    if isinstance(v, bool):
        return None, "must be a number"
    if isinstance(v, (int, float)):
        n = float(v)
    else:
        try:
            n = float(str(v).strip().replace(",", ""))
        except ValueError:
            return None, f"'{norm_text(v)[:30]}' is not a number"
    if math.isnan(n) or math.isinf(n):
        return None, "must be a real number"
    return n, None


def parse_whole(v: Any):
    n, e = parse_number(v)
    if e or n is None:
        return n, e
    if abs(n - round(n)) > 1e-9:
        return None, f"{norm_text(v)} must be a whole number"
    return int(round(n)), None


_DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%y", "%d/%m/%y")


def parse_date(v: Any):
    """Accepts a real Excel date or dd-mm-yyyy text. Returns (date, None) or (None, 'reason')."""
    if is_blank(v):
        return None, None
    d = None
    if isinstance(v, datetime):
        d = v.date()
    elif isinstance(v, date):
        d = v
    elif isinstance(v, str):
        s = v.strip()
        for fmt in _DATE_FORMATS:
            try:
                d = datetime.strptime(s, fmt).date()
                break
            except ValueError:
                continue
    if d is None:
        return None, f"'{norm_text(v)[:30]}' is not a valid date. Write it as dd-mm-yyyy, for example 31-12-2027"
    if not (2000 <= d.year <= 2100):
        return None, f"year {d.year} looks wrong. Write the date as dd-mm-yyyy"
    return d, None


def parse_yn(v: Any, default: bool = True):
    """Returns (bool, None) or (None, 'reason')."""
    if is_blank(v):
        return default, None
    k = norm_key(v)
    if k in ("y", "yes", "true", "1"):
        return True, None
    if k in ("n", "no", "false", "0"):
        return False, None
    return None, f"'{norm_text(v)[:20]}' must be Y or N"


def read_table(wb, sheet_name: str, columns, max_rows: int, issues: list, required_sheet: bool = True):
    """Reads one sheet into [(excel_row_number, {key: raw_value})], skipping empty rows.
    columns = [(key, header_label, required)]. Returns None when the sheet or a required
    column is missing (a problem is added to `issues`)."""
    ws = next((s for s in wb.worksheets if s.title.strip().casefold() == sheet_name.casefold()), None)
    if ws is None:
        if required_sheet:
            issues.append(Issue(sheet_name, None, None, f'Sheet "{sheet_name}" was not found. Download a fresh template.'))
        return None
    try:
        ws.reset_dimensions()
    except Exception:
        pass
    rows = ws.iter_rows(values_only=True)
    header = next(rows, None)
    if header is None:
        issues.append(Issue(sheet_name, None, None, "The sheet is empty."))
        return None
    index = {}
    for i, h in enumerate(header):
        k = header_key(h)
        if k and k not in index:
            index[k] = i
    positions, missing = {}, False
    for key, label, required in columns:
        pos = index.get(header_key(label))
        if pos is None:
            if required:
                issues.append(Issue(sheet_name, 1, label, f'Column "{label}" was not found in the header row. Download a fresh template.'))
                missing = True
        else:
            positions[key] = pos
    if missing:
        return None
    out = []
    for n, row in enumerate(rows, start=2):
        values = {key: (row[positions[key]] if key in positions and positions[key] < len(row) else None)
                  for key, _, _ in columns}
        if all(is_blank(v) for v in values.values()):
            continue
        if len(out) >= max_rows:
            issues.append(Issue(sheet_name, n, None, f"Too many rows (maximum {max_rows}). Split the file into smaller files."))
            break
        out.append((n, values))
    return out