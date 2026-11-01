"""
The single gate every AI Scribe usage point must go through. Combines three
independent reasons AI Scribe can be unavailable — tier doesn't include it
at all (Foundation), the monthly cap (tier + topups) is exhausted, or the
billing cycle has rolled past cycle-end — into one status check, so no
caller can accidentally enforce only one of the three.
"""
from app.models.ai_scribe_topup import AiScribeTopup
from app.utils.billing_cycle import AI_SCRIBE_TIER_CAPS, effective_ai_scribe_cap, is_unlimited, has_ai_scribe_at_all, is_ai_scribe_period_active
from sqlalchemy import func

from app.models.consultation import Consultation
from app.models.doctor import Doctor
from app.utils.pilot import is_pilot, pilot_state
from app.utils.pilot_events import record_pilot_event
from app.utils.timezone import now_ist_naive, ist_today


def _fmt_date(d):
    return d.strftime("%d %b %Y") if d else ""


def pilot_week_usage(db, hospital_id, week_start_dt, week_end_dt):
    """Consultations of this hospital that consumed an AI Scribe credit inside [week_start, week_end).
    Same flag the monthly gate uses (ai_scribe_credit_consumed); stamped by ai_scribe_credit_at."""
    stamp = func.coalesce(Consultation.ai_scribe_credit_at, Consultation.created_at)
    return (
        db.query(func.count(Consultation.id))
        .join(Doctor, Doctor.id == Consultation.doctor_id)
        .filter(
            Doctor.hospital_id == hospital_id,
            Consultation.ai_scribe_credit_consumed == True,  # noqa: E712
            stamp >= week_start_dt,
            stamp < week_end_dt,
        )
        .scalar()
    ) or 0


def _pilot_scribe_status(db, hospital):
    """Weekly-cap status for Pilot 1 / Pilot 2. Same keys as the monthly status, plus pilot fields."""
    s = pilot_state(hospital, ist_today())
    cap = s["weekly_cap"]
    used = pilot_week_usage(db, hospital.id, s["week_start_dt"], s["week_end_dt"]) if s["week"] else 0
    out = {
        "allowed": False, "reason": None, "message": None,
        "used": used, "cap": cap, "topup_remaining": 0, "total_remaining": 0,
        "pilot": True, "pilot_label": s["label"], "week": s["week"], "total_weeks": s["total_weeks"],
        "resets_on": s["resets_on"].isoformat() if s["resets_on"] else None,
        "pilot_end": s["end"].isoformat() if s["end"] else None,
    }
    if s["phase"] == "not_started":
        out["reason"] = "pilot_not_started"
        out["message"] = "The AI scribe pilot has not started yet. You can continue in manual mode."
    elif s["phase"] in ("grace", "expired"):
        out["reason"] = "pilot_ended"
        out["message"] = "The AI scribe pilot has ended. You can continue in manual mode."
    elif used >= cap:
        out["reason"] = "weekly_cap_reached"
        if s["is_last_week"]:
            out["message"] = f"Weekly AI scribe limit reached. The pilot ends on {_fmt_date(s['end'])}. You can continue in manual mode."
        else:
            out["message"] = f"Weekly AI scribe limit reached. It resets on {_fmt_date(s['resets_on'])}. You can continue in manual mode."
    else:
        out["allowed"] = True
        out["total_remaining"] = cap - used
    return out


def _consume_pilot_credit(db, hospital, consultation):
    """Pilot credit: stamps the consultation (so it counts in the current week), then creates the
    one-per-week 'cap reached' Super Admin notification in the SAME transaction."""
    now = now_ist_naive()
    if consultation is not None:
        consultation.ai_scribe_credit_consumed = True
        consultation.ai_scribe_credit_at = now
        db.flush()
    s = pilot_state(hospital, ist_today())
    if s["phase"] == "active" and s["week"]:
        used = pilot_week_usage(db, hospital.id, s["week_start_dt"], s["week_end_dt"])
        cap = s["weekly_cap"]
        if used >= cap:
            record_pilot_event(
                db, hospital, "pilot_cap", f"pilot_cap:{hospital.id}:{s['week_start'].isoformat()}",
                "Pilot weekly limit reached",
                f"{hospital.name}: weekly AI scribe limit reached (week {s['week']}, {min(used, cap)} of {cap})",
            )
    db.commit()


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

    if is_pilot(hospital.tier):
        return _pilot_scribe_status(db, hospital)

    if not has_ai_scribe_at_all(hospital.tier):
        return {"allowed": False, "reason": "not_included_in_tier", "used": 0, "cap": 0, "topup_remaining": 0, "total_remaining": 0}

    if not is_ai_scribe_period_active(hospital, now):
        # Either the cycle hasn't started (no billing_cycle_start set yet)
        # or it has rolled past cycle-end — either way, AI Scribe is off
        # until a super admin sets/renews the cycle (item 4).
        reason = "cycle_not_started" if not hospital.billing_cycle_start else "cycle_ended"
        cap = effective_ai_scribe_cap(hospital)
        return {"allowed": False, "reason": reason, "used": hospital.ai_scribe_consultations_used, "cap": cap, "topup_remaining": 0, "total_remaining": 0}

    if is_unlimited(hospital.tier):
        return {"allowed": True, "reason": None, "used": hospital.ai_scribe_consultations_used, "cap": None, "topup_remaining": 0, "total_remaining": None}

    cap = effective_ai_scribe_cap(hospital)
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


def consume_ai_scribe_credit(db, hospital, consultation=None):
    """Pilots count against the weekly cap (the consultation is stamped here); every other tier
    uses the monthly counter and top-ups exactly as before."""
    if is_pilot(hospital.tier):
        _consume_pilot_credit(db, hospital, consultation)
        return
    _consume_monthly_ai_scribe_credit(db, hospital)


def _consume_monthly_ai_scribe_credit(db, hospital):
    """Call only after a structuring call actually succeeds — never
    pre-charge, since a failed AI call shouldn't cost the hospital a credit.
    Draws from the tier's base cap first, then from active top-ups
    (soonest-expiring first). No-ops (doesn't touch counters) for an
    unlimited tier."""
    if is_unlimited(hospital.tier):
        return

    cap = effective_ai_scribe_cap(hospital) or 0
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