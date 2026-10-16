"""Stored consultation-usage history per hospital: calendar months + anchor-based billing cycles.

An ENDED window is counted once and stored in hospital_usage_snapshots, never updated, so past
figures don't change if consultations are edited later. The window still in progress is computed
live and never stored. "Completed" = confirmed (has a prescription token) and not voided, dated
by created_at. AI Scribe count = the completed ones that consumed an AI Scribe credit.
"""
import csv
import io
import logging
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.consultation import Consultation
from app.models.doctor import Doctor
from app.models.hospital import Hospital
from app.models.hospital_usage_snapshot import HospitalUsageSnapshot
from app.utils.billing_cycle import get_billing_cycle_info, has_ai_scribe_at_all
from app.utils.timezone import now_ist_naive

logger = logging.getLogger(__name__)
MAX_WINDOWS = 120


def count_usage(db, hospital_id, start, end):
    base = (
        db.query(Consultation)
        .join(Doctor, Doctor.id == Consultation.doctor_id)
        .filter(
            Doctor.hospital_id == hospital_id,
            Consultation.token_number.isnot(None),
            Consultation.is_voided.isnot(True),
            Consultation.created_at >= start,
            Consultation.created_at < end,
        )
    )
    completed = base.count()
    ai = base.filter(Consultation.ai_scribe_credit_consumed == True).count()  # noqa: E712
    return completed, ai


def _month_windows(hospital, now):
    first = hospital.created_at or now
    start = first.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    out = []
    while start <= now and len(out) < MAX_WINDOWS:
        end = start + relativedelta(months=1)
        out.append((start, end))
        start = end
    return out


def _cycle_windows(hospital, now):
    """Monthly windows counted from the current anchor, for monthly AND yearly hospitals."""
    anchor = hospital.billing_cycle_start
    if not anchor:
        return []
    first = min(hospital.created_at or anchor, anchor)
    k = 0
    while anchor + relativedelta(months=k) > first and k > -MAX_WINDOWS:
        k -= 1
    out = []
    while len(out) < MAX_WINDOWS:
        start = anchor + relativedelta(months=k)
        if start > now:
            break
        out.append((start, anchor + relativedelta(months=k + 1)))
        k += 1
    return out


def _overlaps(rows, start, end):
    return any(r.period_start < end and start < r.period_end for r in rows)


def ensure_usage_snapshots(db, hospital, now=None):
    """Stores every ENDED window not stored yet. Existing rows are never touched."""
    now = now or now_ist_naive()
    existing = db.query(HospitalUsageSnapshot).filter(HospitalUsageSnapshot.hospital_id == hospital.id).all()
    have = {"month": [r for r in existing if r.period_kind == "month"],
            "cycle": [r for r in existing if r.period_kind == "cycle"]}
    for kind, windows in (("month", _month_windows(hospital, now)), ("cycle", _cycle_windows(hospital, now))):
        for start, end in windows:
            if end > now or _overlaps(have[kind], start, end):
                continue  # still open, or already stored (also skips a re-anchor seam)
            completed, ai = count_usage(db, hospital.id, start, end)
            row = HospitalUsageSnapshot(
                hospital_id=hospital.id, period_kind=kind, period_start=start, period_end=end,
                completed_consultations=completed, ai_scribe_consultations=ai,
                tier=hospital.tier, billing_period=hospital.billing_period or "monthly",
            )
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()  # another request stored it first
                continue
            have[kind].append(row)


def _fmt(start, end, completed, ai, final):
    return {
        "start": start.strftime("%Y-%m-%d"),
        "end": (end - timedelta(days=1)).strftime("%Y-%m-%d"),  # inclusive last day
        "completed": completed, "ai_scribe": ai, "final": final,
    }


def get_usage_history(db, hospital):
    now = now_ist_naive()
    ensure_usage_snapshots(db, hospital, now)
    stored = (
        db.query(HospitalUsageSnapshot)
        .filter(HospitalUsageSnapshot.hospital_id == hospital.id)
        .order_by(HospitalUsageSnapshot.period_start.desc())
        .all()
    )
    rows = {"month": [], "cycle": []}
    for kind, windows in (("month", _month_windows(hospital, now)), ("cycle", _cycle_windows(hospital, now))):
        for start, end in windows:
            if start <= now < end:  # the window in progress: live, never stored
                completed, ai = count_usage(db, hospital.id, start, end)
                rows[kind].append((start, end, completed, ai, False))
    for r in stored:
        rows[r.period_kind].append((r.period_start, r.period_end, r.completed_consultations, r.ai_scribe_consultations, True))

    show_ai = has_ai_scribe_at_all(hospital.tier) or any(r.ai_scribe_consultations for r in stored)

    term = None
    if hospital.billing_period == "yearly" and hospital.billing_cycle_start:
        info = get_billing_cycle_info(hospital)
        t_start, t_end = info["cycle_start"], info["cycle_end"]
        inside = [r for r in rows["cycle"] if r[0] >= t_start and r[1] <= t_end]
        term = _fmt(t_start, t_end, sum(r[2] for r in inside), sum(r[3] for r in inside), now >= t_end)

    return {
        "hospital_id": hospital.id,
        "show_ai": show_ai,
        "months": [_fmt(*r) for r in rows["month"]],
        "cycles": [_fmt(*r) for r in rows["cycle"]],
        "term": term,
    }


def usage_history_csv(hospital, history):
    def safe(v):
        s = str(v)
        return "'" + s if s[:1] and s[:1] in "=+-@" else s

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Hospital", "Type", "Period start", "Period end", "Completed consultations", "AI Scribe consultations", "Status"])
    for label, rows in (("Calendar month", history["months"]), ("Billing cycle", history["cycles"])):
        for r in reversed(rows):  # oldest first
            w.writerow([safe(hospital.name), label, r["start"], r["end"], r["completed"], r["ai_scribe"],
                        "final" if r["final"] else "in progress"])
    t = history["term"]
    if t:
        w.writerow([safe(hospital.name), "Whole plan term", t["start"], t["end"], t["completed"], t["ai_scribe"],
                    "final" if t["final"] else "in progress"])
    return buf.getvalue()


def finalize_usage_snapshots_for_all_hospitals():
    """Scheduler + startup entry point. Add-only and non-fatal per hospital."""
    db = SessionLocal()
    try:
        for h in db.query(Hospital).all():
            try:
                ensure_usage_snapshots(db, h)
            except Exception as e:
                db.rollback()
                logger.warning(f"Usage snapshot failed for hospital {h.id}: {e}")
    finally:
        db.close()