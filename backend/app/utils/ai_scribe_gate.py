"""
The single gate every AI Scribe usage point must go through. Combines three
independent reasons AI Scribe can be unavailable — tier doesn't include it
at all (Foundation), the monthly cap (tier + topups) is exhausted, or the
billing cycle has rolled past cycle-end — into one status check, so no
caller can accidentally enforce only one of the three.
"""
from app.models.ai_scribe_topup import AiScribeTopup
from app.utils.billing_cycle import AI_SCRIBE_TIER_CAPS, is_unlimited, has_ai_scribe_at_all, is_ai_scribe_period_active
from app.utils.timezone import now_ist_naive


def _active_topups(db, hospital_id, now):
    """Unexpired top-ups with remaining balance, soonest-expiring first —
    so usage always drains the block closest to wasting away, not an
    arbitrary one."""
    return (
        db.query(AiScribeTopup)
        .filter(
            AiScribeTopup.hospital_id == hospital_id,
            AiScribeTopup.expires_at > now,
            AiScribeTopup.consultations_used < AiScribeTopup.consultations_granted,
        )
        .order_by(AiScribeTopup.expires_at.asc())
        .all()
    )


def get_ai_scribe_status(db, hospital):
    """Returns a dict describing whether AI Scribe can be used right now,
    and the numbers needed to show a used/total counter. `cap` and
    `total_remaining` are None when the tier is unlimited (Enterprise) —
    callers must handle that explicitly rather than assuming a number."""
    now = now_ist_naive()

    if not has_ai_scribe_at_all(hospital.tier):
        return {"allowed": False, "reason": "not_included_in_tier", "used": 0, "cap": 0, "topup_remaining": 0, "total_remaining": 0}

    if not is_ai_scribe_period_active(hospital, now):
        # Either the cycle hasn't started (no billing_cycle_start set yet)
        # or it has rolled past cycle-end — either way, AI Scribe is off
        # until a super admin sets/renews the cycle (item 4).
        reason = "cycle_not_started" if not hospital.billing_cycle_start else "cycle_ended"
        cap = AI_SCRIBE_TIER_CAPS.get(hospital.tier)
        return {"allowed": False, "reason": reason, "used": hospital.ai_scribe_consultations_used, "cap": cap, "topup_remaining": 0, "total_remaining": 0}

    if is_unlimited(hospital.tier):
        return {"allowed": True, "reason": None, "used": hospital.ai_scribe_consultations_used, "cap": None, "topup_remaining": 0, "total_remaining": None}

    cap = AI_SCRIBE_TIER_CAPS[hospital.tier]
    used = hospital.ai_scribe_consultations_used
    tier_remaining = max(0, cap - used)

    topups = _active_topups(db, hospital.id, now)
    topup_remaining = sum(t.consultations_granted - t.consultations_used for t in topups)

    total_remaining = tier_remaining + topup_remaining
    return {
        "allowed": total_remaining > 0,
        "reason": None if total_remaining > 0 else "cap_reached",
        "used": used, "cap": cap, "topup_remaining": topup_remaining, "total_remaining": total_remaining,
    }


def consume_ai_scribe_credit(db, hospital):
    """Call only after a structuring call actually succeeds — never
    pre-charge, since a failed AI call shouldn't cost the hospital a credit.
    Draws from the tier's base cap first, then from active top-ups
    (soonest-expiring first). No-ops (doesn't touch counters) for an
    unlimited tier."""
    if is_unlimited(hospital.tier):
        return

    cap = AI_SCRIBE_TIER_CAPS.get(hospital.tier, 0)
    if hospital.ai_scribe_consultations_used < cap:
        hospital.ai_scribe_consultations_used += 1
        db.commit()
        return

    now = now_ist_naive()
    topups = _active_topups(db, hospital.id, now)
    if topups:
        topup = topups[0]
        topup.consultations_used += 1
        db.commit()
    else:
        # Shouldn't happen if get_ai_scribe_status was checked first, but
        # never silently let usage go uncounted — record it against the
        # tier counter so the hospital's true usage still shows up
        # somewhere, even past the cap.
        hospital.ai_scribe_consultations_used += 1
        db.commit()