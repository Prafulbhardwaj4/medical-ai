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
# Growth yearly bonus on top of the 60,000 base pool (final: 2,000, so pool = 62,000).
# SINGLE source of truth. Change only this constant.
GROWTH_YEARLY_BONUS_CONSULTATIONS = 2000
AI_SCRIBE_YEARLY_BONUS = {"growth": GROWTH_YEARLY_BONUS_CONSULTATIONS}

# Only these tiers can be sold yearly. Scale/Enterprise stay placeholders until on sale.
YEARLY_SELLABLE_TIERS = ("foundation", "growth")
YEARLY_TERM_MONTHS = {"foundation": 13, "growth": 12}  # Foundation: pay for 12, get 13
YEARLY_LIST_PRICE = {"foundation": 119999, "growth": 349999}  # final yearly prices; Foundation = 13 months of service


def cycle_months(hospital) -> int:
    if getattr(hospital, "billing_period", "monthly") != "yearly":
        return 1
    return YEARLY_TERM_MONTHS.get(hospital.tier, 12)


def effective_ai_scribe_cap(hospital):
    """None = unlimited, 0 = no AI Scribe, otherwise the cap for the CURRENT cycle."""
    base = AI_SCRIBE_TIER_CAPS.get(hospital.tier, 0)
    if not base:
        return base
    if getattr(hospital, "billing_period", "monthly") == "yearly":
        stored = getattr(hospital, "ai_scribe_yearly_allowance", None)
        if stored:
            return stored  # snapshot taken at term start; later constant changes don't touch running terms
        return yearly_ai_scribe_allowance(hospital.tier)
    return base


def yearly_ai_scribe_allowance(tier):
    """One pool for the whole term: 12 x monthly cap + bonus. 0 when the tier has no AI Scribe."""
    base = AI_SCRIBE_TIER_CAPS.get(tier, 0)
    if not base:
        return 0
    return base * 12 + AI_SCRIBE_YEARLY_BONUS.get(tier, 0)


def validate_billing_period(tier, billing_period):
    """Single backend gate for monthly/yearly. Raises ValueError with a user-facing message."""
    if billing_period not in ("monthly", "yearly"):
        raise ValueError("billing_period must be 'monthly' or 'yearly'")
    if billing_period == "yearly" and tier not in YEARLY_SELLABLE_TIERS:
        raise ValueError("Yearly plans are only available for Foundation and Growth")
    return billing_period


def apply_plan_term(hospital):
    """Recomputes the stored term fields from the anchor, tier and period. Call after ANY change
    to billing_cycle_start, tier or billing_period. Monthly hospitals keep both fields NULL so
    they behave exactly as before."""
    if getattr(hospital, "billing_period", "monthly") != "yearly" or not hospital.billing_cycle_start:
        hospital.plan_end_date = None
        hospital.ai_scribe_yearly_allowance = None
        return
    hospital.plan_end_date = hospital.billing_cycle_start + relativedelta(months=cycle_months(hospital))
    hospital.ai_scribe_yearly_allowance = yearly_ai_scribe_allowance(hospital.tier) or None


def monthly_equivalent_price(hospital, tier=None):
    """Per-month revenue contribution for MRR/ARR. Yearly = term price / service months
    (Foundation 119988/13, Growth 349999/12); monthly = list monthly price."""
    tier = tier or hospital.tier
    if getattr(hospital, "billing_period", "monthly") == "yearly" and tier in YEARLY_LIST_PRICE:
        return round(YEARLY_LIST_PRICE[tier] / YEARLY_TERM_MONTHS[tier])
    return TIER_MONTHLY_PRICE.get(tier, 0)


def plan_summary(tier, billing_period):
    """Price and entitlements for one plan. The creation preview reads this, never hardcoded in JS."""
    base = AI_SCRIBE_TIER_CAPS.get(tier, 0) or None
    if billing_period == "yearly":
        months = YEARLY_TERM_MONTHS[tier]
        return {
            "tier": tier, "billing_period": "yearly", "price": YEARLY_LIST_PRICE[tier],
            "service_months": months, "free_months": months - 12,
            "consultations_total": yearly_ai_scribe_allowance(tier) or None,
            "consultations_base": (base * 12) if base else None,
            "consultations_bonus": AI_SCRIBE_YEARLY_BONUS.get(tier) or None,
        }
    return {
        "tier": tier, "billing_period": "monthly", "price": TIER_MONTHLY_PRICE.get(tier, 0),
        "service_months": 1, "free_months": 0,
        "consultations_total": base, "consultations_base": base, "consultations_bonus": None,
    }


GRACE_DAYS = 3           # days after cycle-end that non-AI-Scribe services keep working
RENEW_WINDOW_LEAD_DAYS = 2  # days before cycle-end that the Renew button activates


def get_billing_cycle_info(hospital):
    """Returns None if the hospital hasn't logged in yet (no cycle started).
    Otherwise returns a dict of every date downstream code needs, all
    derived from the single billing_cycle_start anchor."""
    if not hospital.billing_cycle_start:
        return None

    cycle_start = hospital.billing_cycle_start
    stored_end = getattr(hospital, "plan_end_date", None)
    if getattr(hospital, "billing_period", "monthly") == "yearly" and stored_end:
        cycle_end = stored_end  # stored by apply_plan_term: 12 months Growth / 13 months Foundation
    else:
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