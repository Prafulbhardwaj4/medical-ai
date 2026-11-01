"""Pilot 1 / Pilot 2 plans: the ONE place for pilot rules and date math.

Pilots are internal plans controlled only by the Super Admin. They rank equal to
Growth for every tier check and never use the monthly billing cycle. Every gate,
job, serializer and screen calls these functions; nothing else does pilot date math.

All dates are Indian time (IST): callers pass ist_today() / now_ist_naive().
Pilot period = start date up to the day BEFORE the end date.
End date = deadline day. Grace = deadline day + the next day (scribe stopped,
everything else works). Deactivation = from 00:00 IST on end date + 2 days.
"""
from datetime import date, datetime, timedelta

PILOT_1 = "pilot_1"
PILOT_2 = "pilot_2"
PILOT_TIERS = (PILOT_1, PILOT_2)

PILOT_LABELS = {PILOT_1: "Pilot 1", PILOT_2: "Pilot 2"}
PILOT_DAYS = {PILOT_1: 42, PILOT_2: 21}
PILOT_FEE = {PILOT_1: 6000, PILOT_2: 4000}

PILOT_GRACE_DAYS = 2
PILOT_MAX_BACKDATE_DAYS = 60
PILOT_DEFAULT_WEEKLY_CAP = 150
PILOT_MIN_WEEKLY_CAP = 1
PILOT_MAX_WEEKLY_CAP = 1000


def is_pilot(tier) -> bool:
    return tier in PILOT_TIERS


def pilot_label(tier) -> str:
    return PILOT_LABELS.get(tier, "Pilot")


def pilot_total_weeks(tier) -> int:
    return PILOT_DAYS[tier] // 7


def pilot_fee_label(tier) -> str:
    return f"Rs {PILOT_FEE[tier]:,}"


def parse_pilot_start(value, today: date) -> date:
    """YYYY-MM-DD, today or up to 60 days ago. Raises ValueError with a plain message."""
    if not value or not str(value).strip():
        raise ValueError("Pilot start date is required")
    try:
        start = datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Pilot start date must be YYYY-MM-DD")
    if start > today:
        raise ValueError("Pilot start date cannot be in the future")
    if (today - start).days > PILOT_MAX_BACKDATE_DAYS:
        raise ValueError(f"Pilot start date cannot be more than {PILOT_MAX_BACKDATE_DAYS} days ago")
    return start


def validate_weekly_cap(value) -> int:
    """None -> default 150. Otherwise a whole number from 1 to 1000."""
    if value is None:
        return PILOT_DEFAULT_WEEKLY_CAP
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Weekly scribe limit must be a whole number")
    if value < PILOT_MIN_WEEKLY_CAP or value > PILOT_MAX_WEEKLY_CAP:
        raise ValueError(f"Weekly scribe limit must be between {PILOT_MIN_WEEKLY_CAP} and {PILOT_MAX_WEEKLY_CAP}")
    return value


def pilot_end_date(tier, start: date) -> date:
    return start + timedelta(days=PILOT_DAYS[tier])


def pilot_dates(tier, start: date) -> dict:
    end = pilot_end_date(tier, start)
    return {
        "start": start,
        "end": end,                                              # deadline day
        "grace_end": end + timedelta(days=PILOT_GRACE_DAYS - 1),  # last grace day
        "deactivation": end + timedelta(days=PILOT_GRACE_DAYS),   # deactivated from 00:00 IST this day
    }


def apply_pilot_schedule(hospital, tier, start: date, weekly_cap=None) -> None:
    """Stores the pilot dates (and the weekly cap when given) on the hospital row.
    Does not touch tier, billing or payments. Used on create, change-to-pilot and change-dates."""
    hospital.pilot_start_date = start
    hospital.pilot_end_date = pilot_end_date(tier, start)
    if weekly_cap is not None:
        hospital.pilot_weekly_cap = weekly_cap


def pilot_weekly_cap(hospital) -> int:
    return getattr(hospital, "pilot_weekly_cap", None) or PILOT_DEFAULT_WEEKLY_CAP


def pilot_state(hospital, today: date = None):
    """None for a non-pilot hospital. Otherwise the whole pilot position for `today` (IST date).

    phase: "not_started" | "active" | "grace" | "expired"
      active   = start date .. day before end date
      grace    = end date and the day after (scribe stopped)
      expired  = end date + 2 days onward (hospital must be deactivated)
    week     = (today - start) // 7 + 1 while active; frozen at the last week afterwards; 0 before start.
    """
    tier = hospital.tier
    if not is_pilot(tier):
        return None
    if today is None:
        from app.utils.timezone import ist_today
        today = ist_today()

    total_weeks = pilot_total_weeks(tier)
    start = getattr(hospital, "pilot_start_date", None)
    state = {
        "tier": tier, "label": pilot_label(tier), "phase": "not_started",
        "total_weeks": total_weeks, "weekly_cap": pilot_weekly_cap(hospital),
        "week": 0, "week_start": None, "week_end": None,
        "week_start_dt": None, "week_end_dt": None,
        "resets_on": None, "is_last_week": False,
        "start": start, "end": None, "grace_end": None, "deactivation": None,
        "days_left": 0, "grace_days_left": 0, "deactivate_now": False,
    }
    if start is None:
        return state  # pilot tier without dates: scribe stays off, nothing is deactivated

    d = pilot_dates(tier, start)
    end = getattr(hospital, "pilot_end_date", None) or d["end"]
    grace_end = end + timedelta(days=PILOT_GRACE_DAYS - 1)
    deactivation = end + timedelta(days=PILOT_GRACE_DAYS)
    state.update({"end": end, "grace_end": grace_end, "deactivation": deactivation})

    if today < start:
        return state

    week = min(((today - start).days // 7) + 1, total_weeks)
    week_start = start + timedelta(days=7 * (week - 1))
    week_end = week_start + timedelta(days=7)  # exclusive: the next week starts here, 00:00 IST
    state.update({
        "week": week, "week_start": week_start, "week_end": week_end,
        "week_start_dt": datetime(week_start.year, week_start.month, week_start.day),
        "week_end_dt": datetime(week_end.year, week_end.month, week_end.day),
        "resets_on": week_end, "is_last_week": week >= total_weeks,
    })

    if today < end:
        state["phase"] = "active"
        state["days_left"] = (end - today).days
    elif today < deactivation:
        state["phase"] = "grace"
        state["grace_days_left"] = (grace_end - today).days + 1
    else:
        state["phase"] = "expired"
        state["deactivate_now"] = True
    return state


def _iso(d):
    return d.isoformat() if d else None


def pilot_block(hospital, today: date = None) -> dict:
    """Serializer fields for a pilot hospital (Super Admin list and detail). The monthly-billing
    keys are present but empty so the existing card code never sees a missing field."""
    s = pilot_state(hospital, today)
    return {
        "is_pilot": True,
        "pilot_label": s["label"],
        "pilot_phase": s["phase"],
        "pilot_week": s["week"],
        "pilot_total_weeks": s["total_weeks"],
        "pilot_weekly_cap": s["weekly_cap"],
        "pilot_start_date": _iso(s["start"]),
        "pilot_end_date": _iso(s["end"]),
        "pilot_grace_end_date": _iso(s["grace_end"]),
        "pilot_deactivation_date": _iso(s["deactivation"]),
        "pilot_days_left": s["days_left"],
        "pilot_grace_days_left": s["grace_days_left"],
        "pilot_fee": PILOT_FEE[s["tier"]],
        "pilot_result_note": getattr(hospital, "pilot_result_note", None),
        "has_ai_scribe": False,
        "billing_period": "monthly",
        "plan_end_date": None, "plan_service_months": None, "ai_scribe_yearly_allowance": None,
        "ai_scribe_used": None, "ai_scribe_cap": None,
        "ai_scribe_topup_remaining": None, "ai_scribe_total_remaining": None,
        "billing_cycle_start": None, "billing_cycle_end": None,
        "grace_end": None, "deactivation_at": None,
        "renew_window_open": False,
    }