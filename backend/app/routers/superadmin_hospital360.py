# Super Admin "Hospital 360": per-hospital summary, staff, payments, requests and the private notes box.
# Read-only except PUT /notes (explicitly requested; audited without storing the note text in the audit log).
# PRIVACY: staff accounts and money only. No patient names, phones or clinical data are selected here.
# Suggestions are returned without their message text; leads without any phone number.
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.ai_scribe_topup import AiScribeTopup
from app.models.audit_log import AuditLog
from app.models.doctor import Doctor
from app.models.hospital import Hospital
from app.models.hospital_lead import HospitalLead
from app.models.subscription_payment import SubscriptionPayment
from app.models.suggestion import Suggestion
from app.models.upgrade_request import UpgradeRequest
from app.routers.superadmin_overview import _AUDIT_TARGETS, _iso
from app.utils.audit import log_action
from app.utils.rate_limit import limiter
from app.utils.roles import require_super_admin
from app.utils.timezone import now_ist_naive

router = APIRouter(prefix="/admin/sa/hospital", tags=["superadmin-hospital360"])


def _hospital_or_404(db: Session, hospital_id: int):
    row = db.query(Hospital.id, Hospital.name, Hospital.internal_notes).filter(Hospital.id == hospital_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Hospital not found")
    return row


@router.get("/{hospital_id}/360")
@limiter.limit("60/minute")
def hospital_360(
    request: Request,
    hospital_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(require_super_admin),
):
    hosp = _hospital_or_404(db, hospital_id)
    now = now_ist_naive()

    by_role, total, active = {}, 0, 0
    for role, is_active, n in (
        db.query(Doctor.role, Doctor.is_active, func.count(Doctor.id))
        .filter(Doctor.hospital_id == hospital_id)
        .group_by(Doctor.role, Doctor.is_active).all()
    ):
        by_role[role.value] = by_role.get(role.value, 0) + n
        total += n
        if is_active:
            active += n

    pay_count, pay_total = (
        db.query(func.count(SubscriptionPayment.id), func.coalesce(func.sum(SubscriptionPayment.amount), 0))
        .filter(SubscriptionPayment.hospital_id == hospital_id).one()
    )
    last_pay = (
        db.query(SubscriptionPayment.amount, SubscriptionPayment.created_at)
        .filter(SubscriptionPayment.hospital_id == hospital_id)
        .order_by(SubscriptionPayment.created_at.desc()).first()
    )

    up_total = db.query(func.count(UpgradeRequest.id)).filter(UpgradeRequest.hospital_id == hospital_id).scalar() or 0
    up_new = (
        db.query(func.count(UpgradeRequest.id))
        .filter(UpgradeRequest.hospital_id == hospital_id, UpgradeRequest.status == "new").scalar() or 0
    )
    leads = db.query(func.count(HospitalLead.id)).filter(HospitalLead.converted_hospital_id == hospital_id).scalar() or 0
    sugg_new = (
        db.query(func.count(Suggestion.id))
        .filter(Suggestion.hospital_id == hospital_id, Suggestion.status == "sent").scalar() or 0
    )

    act_filter = (AuditLog.hospital_id == hospital_id, AuditLog.target_type.in_(_AUDIT_TARGETS))
    act_30 = db.query(func.count(AuditLog.id)).filter(*act_filter, AuditLog.created_at >= now - timedelta(days=30)).scalar() or 0
    act_last = db.query(func.max(AuditLog.created_at)).filter(*act_filter).scalar()

    return {
        "hospital_id": hosp.id,
        "staff": {"total": total, "active": active, "by_role": by_role},
        "payments": {
            "count": int(pay_count or 0), "total": float(pay_total or 0),
            "last_amount": float(last_pay[0]) if last_pay else None,
            "last_at": _iso(last_pay[1]) if last_pay else None,
        },
        "requests": {"upgrade_total": up_total, "upgrade_new": up_new, "leads_converted": leads, "suggestions_new": sugg_new},
        "activity": {"last_30_days": act_30, "last_at": _iso(act_last)},
        "notes": hosp.internal_notes or "",
    }


@router.get("/{hospital_id}/staff")
@limiter.limit("60/minute")
def hospital_staff(
    request: Request,
    hospital_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(require_super_admin),
):
    _hospital_or_404(db, hospital_id)
    now = now_ist_naive()
    rows = (
        db.query(Doctor).filter(Doctor.hospital_id == hospital_id)
        .order_by(Doctor.role, Doctor.name).limit(500).all()
    )
    return {
        "items": [
            {
                "id": d.id, "title": d.title, "name": d.name, "email": d.email, "phone": d.phone,
                "role": d.role.value, "is_active": bool(d.is_active), "doctor_uid": d.doctor_uid,
                "created_at": _iso(d.created_at),
                "locked": bool(d.locked_until and d.locked_until > now),
                "must_change_password": bool(d.must_change_password),
            }
            for d in rows
        ]
    }


@router.get("/{hospital_id}/payments")
@limiter.limit("60/minute")
def hospital_payments(
    request: Request,
    hospital_id: int,
    page: int = Query(1, ge=1, le=1000),
    page_size: int = Query(15, ge=1, le=50),
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(require_super_admin),
):
    _hospital_or_404(db, hospital_id)
    total = db.query(func.count(SubscriptionPayment.id)).filter(SubscriptionPayment.hospital_id == hospital_id).scalar() or 0
    collected = (
        db.query(func.coalesce(func.sum(SubscriptionPayment.amount), 0))
        .filter(SubscriptionPayment.hospital_id == hospital_id).scalar() or 0
    )
    rows = (
        db.query(SubscriptionPayment, Doctor.name)
        .outerjoin(Doctor, Doctor.id == SubscriptionPayment.collected_by)
        .filter(SubscriptionPayment.hospital_id == hospital_id)
        .order_by(SubscriptionPayment.created_at.desc(), SubscriptionPayment.id.desc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )

    audits = []
    stamped = [p.created_at for p, _ in rows if p.created_at]
    if stamped:
        lo, hi = min(stamped) - timedelta(minutes=2), max(stamped) + timedelta(minutes=2)
        audits = (
            db.query(AuditLog.id, AuditLog.created_at)
            .filter(AuditLog.hospital_id == hospital_id, AuditLog.action == "hospital_billing_cycle_renewed",
                    AuditLog.created_at.between(lo, hi)).all()
        )

    def audit_for(p):
        best = None
        for aid, ac in audits:
            if not p.created_at or not ac:
                continue
            gap = abs((ac - p.created_at).total_seconds())
            if gap <= 120 and (best is None or gap < best[0]):
                best = (gap, aid)
        return best[1] if best else None

    topups = (
        db.query(AiScribeTopup).filter(AiScribeTopup.hospital_id == hospital_id)
        .order_by(AiScribeTopup.purchased_at.desc()).limit(20).all()
    )
    return {
        "page": page, "page_size": page_size, "total": total, "has_more": page * page_size < total,
        "collected_total": float(collected),
        "items": [
            {
                "id": p.id, "tier": p.tier, "billing_period": p.billing_period, "amount": float(p.amount),
                "period_start": _iso(p.period_start), "period_end": _iso(p.period_end),
                "collected_by": by, "note": p.note, "created_at": _iso(p.created_at), "audit_id": audit_for(p),
            }
            for p, by in rows
        ],
        "topups": [
            {
                "id": t.id, "block_size": t.block_size, "price_paid": float(t.price_paid),
                "payment_collected": bool(t.payment_collected), "purchased_at": _iso(t.purchased_at),
                "expires_at": _iso(t.expires_at), "used": t.consultations_used, "granted": t.consultations_granted,
            }
            for t in topups
        ],
    }


@router.get("/{hospital_id}/requests")
@limiter.limit("60/minute")
def hospital_requests(
    request: Request,
    hospital_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(require_super_admin),
):
    _hospital_or_404(db, hospital_id)
    ups = db.query(UpgradeRequest).filter(UpgradeRequest.hospital_id == hospital_id).order_by(UpgradeRequest.created_at.desc()).limit(50).all()
    leads = db.query(HospitalLead).filter(HospitalLead.converted_hospital_id == hospital_id).order_by(HospitalLead.created_at.desc()).limit(50).all()
    sugg = db.query(Suggestion).filter(Suggestion.hospital_id == hospital_id).order_by(Suggestion.created_at.desc()).limit(50).all()
    return {
        "upgrade_requests": [
            {"id": u.id, "requested_tier": u.requested_tier, "status": u.status, "contact_name": u.contact_name,
             "owner": u.owner, "next_follow_up_at": _iso(u.next_follow_up_at), "created_at": _iso(u.created_at)}
            for u in ups
        ],
        "leads": [
            {"id": l.id, "hospital_name": l.hospital_name, "city": l.city, "status": l.status,
             "owner": l.owner, "next_follow_up_at": _iso(l.next_follow_up_at), "created_at": _iso(l.created_at)}
            for l in leads
        ],
        "suggestions": [
            {"id": s.id, "status": s.status, "submitted_by_role": s.submitted_by_role, "created_at": _iso(s.created_at)}
            for s in sugg
        ],
    }


class NotesIn(BaseModel):
    notes: str = Field("", max_length=4000)


@router.put("/{hospital_id}/notes")
@limiter.limit("30/minute")
def save_hospital_notes(
    request: Request,
    hospital_id: int,
    body: NotesIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(require_super_admin),
):
    hosp = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hosp:
        raise HTTPException(status_code=404, detail="Hospital not found")
    text = body.notes.replace("\x00", "").strip()
    hosp.internal_notes = text or None
    db.commit()
    log_action(
        db, current_doctor, action="hospital_notes_updated", target_type="hospital", target_id=hosp.id,
        target_label=hosp.name, details=f"Internal notes updated ({len(text)} characters)", hospital_id=hosp.id,
    )
    return {"notes": text, "updated_at": _iso(now_ist_naive())}