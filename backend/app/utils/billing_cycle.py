"""
Billing-cycle math for the per-hospital AI Scribe subscription (see Part 4
of the build brief). Kept in one place because the same cutoff/grace/renew-
window dates are needed from three different places: the AI Scribe gate,
the deactivation sweep, and the super-admin Renew button's enable/disable
state — duplicating this logic across those would be exactly the kind of
drift that causes the deactivation date to disagree with what the UI shows.

Foundation gets no AI Scribe at all (Part 2) — cap 0, and nothing in the UI
should show a top-up option or a "used/total" counter for it (per Praful).
Scale/Enterprise aren't sold yet (per the brief) but the real caps are set
now anyway — Enterprise is genuinely unlimited (None), not a big number, so
nothing downstream can misread a placeholder as a real ceiling.
"""
from datetime import timedelta
from dateutil.relativedelta import relativedelta

AI_SCRIBE_TIER_CAPS = {
    "foundation": 0,        # no AI Scribe on Foundation at all — never show topup/used-total UI for this tier
    "growth": 5000,
    "scale": 10000,
    "enterprise": None,     # None = unlimited, not a numeric cap — handle this explicitly wherever caps are checked or displayed
}


def is_unlimited(hospital_tier: str) -> bool:
    return AI_SCRIBE_TIER_CAPS.get(hospital_tier) is None


def has_ai_scribe_at_all(hospital_tier: str) -> bool:
    """Foundation has no AI Scribe entitlement — distinct from 'unlimited'
    (None) and distinct from 'capped at some number'. Callers should check
    this before showing any topup/usage UI at all."""
    return AI_SCRIBE_TIER_CAPS.get(hospital_tier, 0) != 0

AI_SCRIBE_TOPUP_PRICING = {
    250: 2999,
    350: 3999,
    500: 4999,
}

TIER_MONTHLY_PRICE = {
    "foundation": 9999,
    "growth": 29999,
    "scale": 44999,       # not sellable yet, priced now per the pricing decision
    "enterprise": 0,      # quotation-based — no fixed number to sum without per-hospital custom pricing storage
}

# Yearly plans: the AI Scribe allowance is one pool for the whole 12-month cycle
# (12 x monthly cap) plus the advertised yearly bonus (tier-catalog.js yearlyBenefit).
AI_SCRIBE_YEARLY_BONUS = {"growth": 2000, "scale": 5000}


def cycle_months(hospital) -> int:
    return 12 if getattr(hospital, "billing_period", "monthly") == "yearly" else 1


def effective_ai_scribe_cap(hospital):
    """None = unlimited, 0 = no AI Scribe, otherwise the cap for the CURRENT cycle."""
    base = AI_SCRIBE_TIER_CAPS.get(hospital.tier, 0)
    if not base:
        return base
    if cycle_months(hospital) == 12:
        return base * 12 + AI_SCRIBE_YEARLY_BONUS.get(hospital.tier, 0)
    return base


GRACE_DAYS = 3           # days after cycle-end that non-AI-Scribe services keep working
RENEW_WINDOW_LEAD_DAYS = 2  # days before cycle-end that the Renew button activates


def get_billing_cycle_info(hospital):
    """Returns None if the hospital hasn't logged in yet (no cycle started).
    Otherwise returns a dict of every date downstream code needs, all
    derived from the single billing_cycle_start anchor."""
    if not hospital.billing_cycle_start:
        return None

    cycle_start = hospital.billing_cycle_start
    cycle_end = cycle_start + relativedelta(months=cycle_months(hospital))
    grace_end = cycle_end + timedelta(days=GRACE_DAYS)              # last moment non-Scribe services work
    deactivation_at = grace_end + timedelta(days=1)                  # deactivation begins the day after grace ends
    renew_window_start = cycle_end - timedelta(days=RENEW_WINDOW_LEAD_DAYS)
    renew_window_end = grace_end

    return {
        "cycle_start": cycle_start,
        "cycle_end": cycle_end,
        "grace_end": grace_end,
        "deactivation_at": deactivation_at,
        "renew_window_start": renew_window_start,
        "renew_window_end": renew_window_end,
    }


def is_ai_scribe_period_active(hospital, now):
    """AI Scribe stops the moment the cycle ends — no grace for this part."""
    info = get_billing_cycle_info(hospital)
    if not info:
        return False
    return now < info["cycle_end"]


def is_renew_window_open(hospital, now):
    info = get_billing_cycle_info(hospital)
    if not info:
        return False
    return info["renew_window_start"] <= now <= info["renew_window_end"]


def is_past_grace(hospital, now):
    """True once the hospital should be (or already is) deactivated."""
    info = get_billing_cycle_info(hospital)
    if not info:
        return False
    return now >= info["deactivation_at"]