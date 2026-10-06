"""Structured numeric reference ranges and High/Low flagging (Phase 3 item 1).

The admin keeps typing the readable range ("13.0-17.0"); the numeric low/high
per sex are derived from it on every catalog save (see the model listeners) and
stored in their own columns, so flagging never has to re-parse free text.
Free text stays as the display fallback for tests whose range can't be parsed.
"""
import re

_NUM = re.compile(r"-?\d+\.?\d*")
NA_TEXT = "Range not available for this patient (sex not recorded)"


def parse_range_bounds(range_str):
    """'13.0-17.0' -> (13.0, 17.0); '<5' -> (None, 5.0); '>2.5' -> (2.5, None); else None."""
    if not range_str:
        return None
    cleaned = str(range_str).replace(",", "").strip()
    low_txt = cleaned.lower()
    nums = re.findall(r"\d+\.?\d*", cleaned)
    if cleaned.startswith("<") or "less" in low_txt or "upto" in low_txt or "up to" in low_txt:
        return (None, float(nums[0])) if nums else None
    if cleaned.startswith(">") or "greater" in low_txt or "above" in low_txt:
        return (float(nums[0]), None) if nums else None
    # Split only on a dash/"to" that directly follows a digit, so "0.6-1.1" stays two positive bounds.
    parts = re.split(r"(?<=\d)\s*(?:-|–|—|\bto\b)\s*", cleaned)
    if len(parts) == 2:
        lo = re.findall(r"\d+\.?\d*", parts[0])
        hi = re.findall(r"\d+\.?\d*", parts[1])
        if lo and hi:
            return float(lo[0]), float(hi[0])
    return None


def pick_range_text(gender, male_r, female_r):
    """Display range for the patient's sex. If sex isn't male/female, only show a
    range when both sexes share it; otherwise say it's unavailable (never a silent female default)."""
    g = (gender or "").strip().lower()
    male_r = (male_r or "").strip()
    female_r = (female_r or "").strip()
    if g == "male":
        return male_r or female_r
    if g == "female":
        return female_r or male_r
    if male_r and male_r == female_r:
        return male_r
    return NA_TEXT if (male_r or female_r) else ""


def bounds_for_patient(gender, obj):
    """(low, high, status). status: 'ok' numeric range applies, 'na' sex unknown and the
    sexes differ, 'none' no structured range stored (caller falls back to free text)."""
    g = (gender or "").strip().lower()
    lm, hm = getattr(obj, "ref_low_male", None), getattr(obj, "ref_high_male", None)
    lf, hf = getattr(obj, "ref_low_female", None), getattr(obj, "ref_high_female", None)
    has_m = lm is not None or hm is not None
    has_f = lf is not None or hf is not None
    if not has_m and not has_f:
        return (None, None, "none")
    if g == "male":
        return (lm, hm, "ok") if has_m else (lf, hf, "ok")
    if g == "female":
        return (lf, hf, "ok") if has_f else (lm, hm, "ok")
    if has_m and has_f and (lm, hm) == (lf, hf):
        return (lm, hm, "ok")
    return (None, None, "na")


def row_fields(gender, obj):
    """Numeric range fields for one result row (also frozen into the result snapshot)."""
    low, high, status = bounds_for_patient(gender, obj)
    return {
        "low": low, "high": high, "range_status": status,
        "crit_low": getattr(obj, "critical_low", None), "crit_high": getattr(obj, "critical_high", None),
    }


def flag_for_value(value, low, high, status, crit_low=None, crit_high=None):
    """'' (not numeric / no structured range), 'N', 'H', 'L', 'CH', 'CL' or 'NA'."""
    if value is None:
        return ""
    m = _NUM.search(str(value).replace(",", "").strip())
    if not m:
        return ""
    try:
        v = float(m.group())
    except ValueError:
        return ""
    if crit_low is not None and v < crit_low:
        return "CL"
    if crit_high is not None and v > crit_high:
        return "CH"
    if status == "na":
        return "NA"
    if status != "ok":
        return ""
    if low is not None and v < low:
        return "L"
    if high is not None and v > high:
        return "H"
    return "N"


def flag_for_row(value, rf):
    if not rf:
        return ""
    return flag_for_value(value, rf.get("low"), rf.get("high"), rf.get("range_status"), rf.get("crit_low"), rf.get("crit_high"))