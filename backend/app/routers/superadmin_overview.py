# Super Admin read-only helpers: Overview ("needs attention"), global search, activity feed.
#
# Design decisions (kept here, not in chat):
# - Read-only. Every endpoint is super_admin only and rate-limited.
# - Counts, sums and plan mix are computed in SQL (GROUP BY / COUNT / SUM). Per-hospital date maths
#   (billing cycle, pilot phase) runs only on NARROW column tuples, pre-filtered in SQL to hospitals
#   that can possibly matter. No ORM Hospital objects are loaded, except the handful of active pilots.
# - PRIVACY: nothing here selects, returns or searches patient names, phones or clinical data.
#   HospitalLead.contact_phone belongs to a patient account, so leads are searched by hospital
#   name / city / state / location only and the phone is never returned.
#   Audit rows are limited to _AUDIT_TARGETS (hospital / staff / lead / request / inquiry actions);
#   patient, consultation, invoice etc. audit rows are never exposed here.
# - All dates are naive IST (same as the database). The frontend formats them as IST.
# - Links are plain hash routes understood by frontend/js/superadmin-shell.js.
from datetime import timedelta
from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.doctor import Doctor
from app.models.hospital import Hospital
from app.models.hospital_lead import HospitalLead
from app.models.plan_inquiry import PlanInquiry
from app.models.subscription_payment import SubscriptionPayment
from app.models.suggestion import Suggestion
from app.models.superadmin_event import SuperAdminEvent  # noqa: F401  (kept for parity with admin.py imports)
from app.models.upgrade_request import UpgradeRequest
from app.utils.ai_scribe_gate import get_ai_scribe_status, has_ai_scribe_at_all
from app.utils.billing_cycle import (
    effective_ai_scribe_cap,
    get_billing_cycle_info,
    monthly_equivalent_price,
)
from app.utils.pilot import PILOT_TIERS, pilot_state
from app.utils.rate_limit import limiter
from app.utils.roles import require_super_admin
from app.utils.timezone import ist_today, now_ist_naive

router = APIRouter(prefix="/admin/sa", tags=["superadmin-overview"])

# Audit rows a Super Admin may see here. Everything patient-related is deliberately absent.
_AUDIT_TARGETS = ("hospital", "doctor", "hospital_lead", "upgrade_request", "plan_inquiry")

_RENEW_LOOKAHEAD_DAYS = 7
_SEV_RANK = {"critical": 0, "warning": 1, "info": 2}
_KIND_RANK = {
    "pilot_expired": 0, "pilot_deadline": 1, "billing_overdue": 2, "billing_grace": 3,
    "pilot_grace": 4, "pilot_cap": 5, "scribe_cap": 6, "billing_ending": 7,
    "deactivated": 8, "scribe_near": 9,
}


def _iso(d):
    return d.isoformat() if d else None


def _like(q: str) -> str:
    """Escapes % _ and \\ so user text is matched literally."""
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _fmt_date(d) -> str:
    return d.strftime("%d %b %Y") if d else "-"


def _audit_item(a, hospital_name):
    return {
        "id": a.id,
        "action": a.action,
        "actor_name": a.actor_name,
        "actor_role": a.actor_role,
        "hospital_id": a.hospital_id,
        "hospital_name": hospital_name,
        "target_type": a.target_type,
        "target_id": a.target_id,
        "target_label": a.target_label,
        "details": (a.details or "")[:160] or None,
        "created_at": _iso(a.created_at),
    }


# ---------------------------------------------------------------- OVERVIEW

@router.get("/overview")
@limiter.limit("60/minute")
def sa_overview(
    request: Request,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(require_super_admin),
):
    now = now_ist_naive()
    today = ist_today()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_month_start = (month_start - timedelta(days=1)).replace(day=1)

    # ---- KPIs (SQL aggregates) ----
    total_h = db.query(func.count(Hospital.id)).scalar() or 0
    active_h = db.query(func.count(Hospital.id)).filter(Hospital.is_active == True).scalar() or 0  # noqa: E712
    new_h = db.query(func.count(Hospital.id)).filter(Hospital.created_at >= month_start).scalar() or 0

    plan_mix, mrr = {}, 0
    mix_rows = (
        db.query(Hospital.tier, Hospital.billing_period, func.count(Hospital.id))
        .filter(Hospital.is_active == True)  # noqa: E712
        .group_by(Hospital.tier, Hospital.billing_period)
        .all()
    )
    for tier, bp, cnt in mix_rows:
        plan_mix[tier] = plan_mix.get(tier, 0) + cnt
        mrr += monthly_equivalent_price(SimpleNamespace(tier=tier, billing_period=bp or "monthly")) * cnt

    staff_total = db.query(func.count(Doctor.id)).filter(Doctor.hospital_id.isnot(None)).scalar() or 0
    staff_active = (
        db.query(func.count(Doctor.id))
        .filter(Doctor.hospital_id.isnot(None), Doctor.is_active == True)  # noqa: E712
        .scalar() or 0
    )

    def _collected(start=None, end=None):
        qy = db.query(func.coalesce(func.sum(SubscriptionPayment.amount), 0), func.count(SubscriptionPayment.id))
        if start is not None:
            qy = qy.filter(SubscriptionPayment.created_at >= start)
        if end is not None:
            qy = qy.filter(SubscriptionPayment.created_at < end)
        amount, count = qy.one()
        return float(amount or 0), int(count or 0)

    coll_month, coll_month_n = _collected(month_start)
    coll_prev, _ = _collected(prev_month_start, month_start)
    coll_total, _ = _collected()

    # ---- Needs attention + renewals + AI usage ----
    items, renewals, scribe_rows = [], [], []

    def add(sev, kind, hid, name, title, detail, when=None, link=None):
        items.append({
            "severity": sev, "kind": kind, "hospital_id": hid, "hospital_name": name,
            "title": title, "detail": detail, "when": _iso(when),
            "link": link or f"#/hospital/{hid}",
        })

    # Paid hospitals whose cycle can end within the look-ahead window (SQL superset, exact maths below).
    la = now + timedelta(days=_RENEW_LOOKAHEAD_DAYS)
    narrow = (
        Hospital.id, Hospital.name, Hospital.tier, Hospital.billing_period, Hospital.billing_cycle_start,
        Hospital.plan_end_date, Hospital.ai_scribe_yearly_allowance, Hospital.ai_scribe_consultations_used,
    )
    cycle_rows = (
        db.query(*narrow)
        .filter(
            Hospital.is_active == True,  # noqa: E712
            Hospital.billing_cycle_start.isnot(None),
            Hospital.tier.notin_(PILOT_TIERS),
            or_(
                and_(Hospital.billing_period == "yearly", Hospital.plan_end_date.isnot(None), Hospital.plan_end_date <= la),
                and_(Hospital.billing_period == "yearly", Hospital.plan_end_date.is_(None),
                     Hospital.billing_cycle_start <= now - timedelta(days=330)),
                and_(or_(Hospital.billing_period.is_(None), Hospital.billing_period != "yearly"),
                     Hospital.billing_cycle_start <= now - timedelta(days=28 - _RENEW_LOOKAHEAD_DAYS)),
            ),
        )
        .all()
    )
    renewal_ids = []
    for r in cycle_rows:
        info = get_billing_cycle_info(r)
        if not info:
            continue
        end, deact = info["cycle_end"], info["deactivation_at"]
        if now >= deact:
            add("critical", "billing_overdue", r.id, r.name, "Past grace, deactivation pending",
                f"Cycle ended {_fmt_date(end)}; not renewed.", end)
            status = "overdue"
        elif end <= now:
            add("critical", "billing_grace", r.id, r.name, "In grace period",
                f"Cycle ended {_fmt_date(end)}; deactivates {_fmt_date(deact)}.", end)
            status = "grace"
        elif (end - now) <= timedelta(days=2):
            add("warning", "billing_ending", r.id, r.name, "Billing cycle ending soon",
                f"Cycle ends {_fmt_date(end)}.", end)
            status = "due_soon"
        elif end <= la:
            status = "upcoming"
        else:
            continue
        renewal_ids.append(r.id)
        renewals.append({
            "hospital_id": r.id, "hospital_name": r.name, "tier": r.tier,
            "billing_period": r.billing_period or "monthly", "cycle_end": _iso(end), "status": status,
            "expected_amount": monthly_equivalent_price(r) if (r.billing_period or "monthly") != "yearly" else None,
            "last_paid_amount": None, "last_paid_at": None,
        })

    if renewal_ids:
        seen_paid = set()
        for p in (
            db.query(SubscriptionPayment)
            .filter(SubscriptionPayment.hospital_id.in_(renewal_ids))
            .order_by(SubscriptionPayment.created_at.desc())
            .limit(500).all()
        ):
            if p.hospital_id in seen_paid:
                continue
            seen_paid.add(p.hospital_id)
            for rn in renewals:
                if rn["hospital_id"] == p.hospital_id:
                    rn["last_paid_amount"] = float(p.amount)
                    rn["last_paid_at"] = _iso(p.created_at)
    renewals.sort(key=lambda x: x["cycle_end"] or "")

    # AI scribe on paid plans: reached / near limit (narrow tuples, only tiers that have a numeric cap).
    for r in (
        db.query(*narrow)
        .filter(Hospital.is_active == True, Hospital.tier.in_(("growth", "scale")),  # noqa: E712
                Hospital.ai_scribe_consultations_used > 0)
        .all()
    ):
        if not has_ai_scribe_at_all(r.tier):
            continue
        cap = effective_ai_scribe_cap(r)
        if not cap:
            continue
        used = r.ai_scribe_consultations_used or 0
        pct = round(used * 100.0 / cap, 1)
        if pct >= 80:
            scribe_rows.append({"hospital_id": r.id, "hospital_name": r.name, "kind": "monthly" if (r.billing_period or "monthly") != "yearly" else "yearly",
                                "used": used, "cap": cap, "percent": pct})
            if used >= cap:
                add("warning", "scribe_cap", r.id, r.name, "AI scribe limit reached", f"{used} of {cap} used on this plan.")
            else:
                add("info", "scribe_near", r.id, r.name, "AI scribe near limit", f"{used} of {cap} used ({pct}%).")

    # Active pilots (a handful): phase, deadline, weekly limit.
    for h in db.query(Hospital).filter(Hospital.is_active == True, Hospital.tier.in_(PILOT_TIERS)).all():  # noqa: E712
        st = pilot_state(h, today)
        if not st:
            continue
        label = st["label"]
        if st["phase"] == "expired" or st["deactivate_now"]:
            add("critical", "pilot_expired", h.id, h.name, f"{label} expired, deactivation due",
                f"Deadline was {_fmt_date(st['end'])}.")
        elif st["phase"] == "grace":
            add("critical", "pilot_grace", h.id, h.name, f"{label} in grace period",
                f"Scribe stopped; deactivates {_fmt_date(st['deactivation'])}.")
        elif st["end"] and st["end"] == today:
            add("critical", "pilot_deadline", h.id, h.name, f"{label} deadline is today", "Decide: convert to a paid plan or let it end.")
        if st["phase"] == "active":
            used = get_ai_scribe_status(db, h)["used"]
            cap = st["weekly_cap"]
            scribe_rows.append({"hospital_id": h.id, "hospital_name": h.name, "kind": "pilot_week",
                                "used": used, "cap": cap, "percent": round(used * 100.0 / cap, 1) if cap else 0,
                                "week": st["week"], "total_weeks": st["total_weeks"]})
            if cap and used >= cap:
                add("warning", "pilot_cap", h.id, h.name, f"{label} weekly scribe limit reached", f"{used} of {cap} this week.")

    # Recently deactivated hospitals (manual or automatic) that are still inactive.
    seen_deact = set()
    for a, hname in (
        db.query(AuditLog, Hospital.name)
        .join(Hospital, Hospital.id == AuditLog.target_id)
        .filter(
            AuditLog.target_type == "hospital",
            AuditLog.action.in_(("hospital_deactivated", "hospital_auto_deactivated")),
            AuditLog.created_at >= now - timedelta(days=14),
            Hospital.is_active == False,  # noqa: E712
        )
        .order_by(AuditLog.created_at.desc()).limit(20).all()
    ):
        if a.target_id in seen_deact:
            continue
        seen_deact.add(a.target_id)
        add("warning", "deactivated", a.target_id, hname, "Hospital is deactivated",
            f"Deactivated {_fmt_date(a.created_at)} by {a.actor_name}.", a.created_at)

    items.sort(key=lambda x: (_SEV_RANK.get(x["severity"], 3), _KIND_RANK.get(x["kind"], 99), (x["hospital_name"] or "").lower()))
    scribe_rows.sort(key=lambda x: -x["percent"])

    # ---- Waiting for the owner (counts + latest 3, no patient data) ----
    def _count(model, col, val):
        return db.query(func.count(model.id)).filter(col == val).scalar() or 0

    waiting = {
        "plan_inquiries": {
            "new": _count(PlanInquiry, PlanInquiry.status, "new"),
            "latest": [
                {"id": x.id, "label": x.hospital_name, "sub": f"{x.requested_tier} - {x.city}", "created_at": _iso(x.created_at)}
                for x in db.query(PlanInquiry).filter(PlanInquiry.status == "new").order_by(PlanInquiry.created_at.desc()).limit(3).all()
            ],
        },
        "hospital_leads": {
            "new": _count(HospitalLead, HospitalLead.status, "new"),
            "latest": [
                {"id": x.id, "label": x.hospital_name, "sub": x.city, "created_at": _iso(x.created_at)}
                for x in db.query(HospitalLead).filter(HospitalLead.status == "new").order_by(HospitalLead.created_at.desc()).limit(3).all()
            ],
        },
        "upgrade_requests": {
            "new": _count(UpgradeRequest, UpgradeRequest.status, "new"),
            "latest": [
                {"id": u.id, "hospital_id": u.hospital_id, "label": hn, "sub": u.requested_tier, "created_at": _iso(u.created_at)}
                for u, hn in db.query(UpgradeRequest, Hospital.name)
                .join(Hospital, Hospital.id == UpgradeRequest.hospital_id)
                .filter(UpgradeRequest.status == "new").order_by(UpgradeRequest.created_at.desc()).limit(3).all()
            ],
        },
        "suggestions": {
            "new": _count(Suggestion, Suggestion.status, "sent"),
            "latest": [
                {"id": s.id, "hospital_id": s.hospital_id, "label": s.hospital_name or "Patient suggestion",
                 "sub": s.submitted_by_role, "created_at": _iso(s.created_at)}
                for s in db.query(Suggestion).filter(Suggestion.status == "sent").order_by(Suggestion.created_at.desc()).limit(3).all()
            ],
        },
    }

    # ---- Recent activity (allow-listed audit rows only) ----
    activity = [
        _audit_item(a, hn)
        for a, hn in db.query(AuditLog, Hospital.name)
        .outerjoin(Hospital, Hospital.id == AuditLog.hospital_id)
        .filter(AuditLog.target_type.in_(_AUDIT_TARGETS))
        .order_by(AuditLog.created_at.desc()).limit(12).all()
    ]

    # ---- Unread notification summary (reuses the existing feed so counts always match the bell) ----
    from app.routers.admin import get_notifications_feed
    feed = get_notifications_feed(db=db, current_doctor=current_doctor)
    unread_items = [n for n in feed["notifications"] if n.get("unread")][:6]
    notifications = {
        "unread_count": feed["unread_count"],
        "items": [
            {"id": n["id"], "severity": n["severity"], "title": n["title"], "message": n["message"],
             "created_at": n["created_at"], "nav_section": n["nav_section"], "hospital_id": n.get("hospital_id"),
             "computed": bool(n.get("computed"))}
            for n in unread_items
        ],
    }

    return {
        "generated_at": _iso(now),
        "kpis": {
            "total_hospitals": total_h, "active_hospitals": active_h, "inactive_hospitals": total_h - active_h,
            "new_hospitals_this_month": new_h, "plan_mix": plan_mix,
            "staff_total": staff_total, "staff_active": staff_active,
            "expected_mrr": mrr,
            "collected_this_month": coll_month, "collected_this_month_count": coll_month_n,
            "collected_last_month": coll_prev, "collected_total": coll_total,
        },
        "attention": {"total": len(items), "items": items[:40]},
        "renewals": renewals[:20],
        "scribe_usage": scribe_rows[:10],
        "waiting": waiting,
        "activity": activity,
        "notifications": notifications,
    }


# ---------------------------------------------------------------- SEARCH

@router.get("/search")
@limiter.limit("120/minute")
def sa_search(
    request: Request,
    q: str = Query("", max_length=60),
    limit: int = Query(5, ge=1, le=10),
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(require_super_admin),
):
    q = (q or "").strip()
    empty = {"q": q, "hospitals": [], "staff": [], "leads": [], "inquiries": [], "requests": [], "payments": [], "audit": []}
    if len(q) < 2:
        return empty
    pat = _like(q)
    out = dict(empty)

    out["hospitals"] = [
        {"id": h.id, "label": h.name, "sub": " - ".join(x for x in (h.hospital_code, h.city) if x),
         "hospital_id": h.id, "hospital_name": h.name, "link": f"#/hospital/{h.id}"}
        for h in db.query(Hospital.id, Hospital.name, Hospital.hospital_code, Hospital.city)
        .filter(or_(Hospital.name.ilike(pat, escape="\\"), Hospital.hospital_code.ilike(pat, escape="\\"),
                    Hospital.city.ilike(pat, escape="\\")))
        .order_by(Hospital.name).limit(limit).all()
    ]

    out["staff"] = [
        {"id": d.id, "label": f"{d.title} {d.name}".strip(), "sub": f"{d.role.value} - {d.email}",
         "hospital_id": d.hospital_id, "hospital_name": hn, "link": f"#/hospital/{d.hospital_id}/staff"}
        for d, hn in db.query(Doctor, Hospital.name)
        .join(Hospital, Hospital.id == Doctor.hospital_id)
        .filter(or_(Doctor.name.ilike(pat, escape="\\"), Doctor.email.ilike(pat, escape="\\"),
                    Doctor.phone.ilike(pat, escape="\\"), Doctor.doctor_uid.ilike(pat, escape="\\")))
        .order_by(Doctor.name).limit(limit).all()
    ]

    # Hospital leads come from patients: search by hospital/place only, never by (or returning) the phone.
    out["leads"] = [
        {"id": x.id, "label": x.hospital_name, "sub": " - ".join(v for v in (x.city, x.state, x.status) if v),
         "hospital_id": x.converted_hospital_id, "hospital_name": None, "link": f"#/hospital-leads?id={x.id}"}
        for x in db.query(HospitalLead)
        .filter(or_(HospitalLead.hospital_name.ilike(pat, escape="\\"), HospitalLead.city.ilike(pat, escape="\\"),
                    HospitalLead.state.ilike(pat, escape="\\"), HospitalLead.location.ilike(pat, escape="\\")))
        .order_by(HospitalLead.created_at.desc()).limit(limit).all()
    ]

    out["inquiries"] = [
        {"id": x.id, "label": x.hospital_name, "sub": f"{x.contact_name} - {x.requested_tier} - {x.status}",
         "hospital_id": None, "hospital_name": None, "link": f"#/plan-inquiries?id={x.id}"}
        for x in db.query(PlanInquiry)
        .filter(or_(PlanInquiry.hospital_name.ilike(pat, escape="\\"), PlanInquiry.contact_name.ilike(pat, escape="\\"),
                    PlanInquiry.contact_phone.ilike(pat, escape="\\"), PlanInquiry.contact_email.ilike(pat, escape="\\"),
                    PlanInquiry.city.ilike(pat, escape="\\")))
        .order_by(PlanInquiry.created_at.desc()).limit(limit).all()
    ]

    out["requests"] = [
        {"id": u.id, "label": f"Upgrade to {u.requested_tier}", "sub": f"{u.contact_name} - {u.status}",
         "hospital_id": u.hospital_id, "hospital_name": hn, "link": f"#/upgrade-requests?id={u.id}"}
        for u, hn in db.query(UpgradeRequest, Hospital.name)
        .join(Hospital, Hospital.id == UpgradeRequest.hospital_id)
        .filter(or_(Hospital.name.ilike(pat, escape="\\"), UpgradeRequest.contact_name.ilike(pat, escape="\\"),
                    UpgradeRequest.contact_phone.ilike(pat, escape="\\"), UpgradeRequest.contact_email.ilike(pat, escape="\\"),
                    UpgradeRequest.requested_tier.ilike(pat, escape="\\")))
        .order_by(UpgradeRequest.created_at.desc()).limit(limit).all()
    ]

    pay_cond = [Hospital.name.ilike(pat, escape="\\"), Hospital.hospital_code.ilike(pat, escape="\\"),
                SubscriptionPayment.tier.ilike(pat, escape="\\"), SubscriptionPayment.note.ilike(pat, escape="\\")]
    if q.isdigit() and len(q) <= 9:
        pay_cond.append(SubscriptionPayment.amount == float(q))
    out["payments"] = [
        {"id": p.id, "label": f"{p.tier} {p.billing_period} payment", "sub": _fmt_date(p.created_at),
         "amount": float(p.amount), "created_at": _iso(p.created_at),
         "hospital_id": p.hospital_id, "hospital_name": hn, "link": f"#/hospital/{p.hospital_id}/payments"}
        for p, hn in db.query(SubscriptionPayment, Hospital.name)
        .join(Hospital, Hospital.id == SubscriptionPayment.hospital_id)
        .filter(or_(*pay_cond))
        .order_by(SubscriptionPayment.created_at.desc()).limit(limit).all()
    ]

    act_pat = _like(q.replace(" ", "_"))
    out["audit"] = [
        {**_audit_item(a, hn), "label": a.action.replace("_", " "),
         "sub": " - ".join(v for v in (a.actor_name, a.target_label) if v),
         "link": f"#/hospital/{a.hospital_id}/activity" if a.hospital_id else "#/activity"}
        for a, hn in db.query(AuditLog, Hospital.name)
        .outerjoin(Hospital, Hospital.id == AuditLog.hospital_id)
        .filter(AuditLog.target_type.in_(_AUDIT_TARGETS),
                or_(Hospital.name.ilike(pat, escape="\\"), AuditLog.target_label.ilike(pat, escape="\\"),
                    AuditLog.action.ilike(act_pat, escape="\\")))
        .order_by(AuditLog.created_at.desc()).limit(limit).all()
    ]
    return out


# ---------------------------------------------------------------- ACTIVITY (paginated)

@router.get("/activity")
@limiter.limit("60/minute")
def sa_activity(
    request: Request,
    hospital_id: Optional[int] = Query(None, ge=1),
    audit_id: Optional[int] = Query(None, ge=1),
    page: int = Query(1, ge=1, le=1000),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(require_super_admin),
):
    conds = [AuditLog.target_type.in_(_AUDIT_TARGETS)]
    if hospital_id:
        conds.append(AuditLog.hospital_id == hospital_id)
    if audit_id:
        conds.append(AuditLog.id == audit_id)
    total = db.query(func.count(AuditLog.id)).filter(*conds).scalar() or 0
    rows = (
        db.query(AuditLog, Hospital.name)
        .outerjoin(Hospital, Hospital.id == AuditLog.hospital_id)
        .filter(*conds)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    return {
        "page": page, "page_size": page_size, "total": total,
        "has_more": page * page_size < total,
        "items": [_audit_item(a, hn) for a, hn in rows],
    }