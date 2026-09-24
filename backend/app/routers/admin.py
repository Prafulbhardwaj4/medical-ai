from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.hospital import Hospital
from app.models.doctor import Doctor, UserRole
from app.config import settings
import secrets
from app.utils.auth import hash_password, get_current_doctor, now_ist_naive, ist_today, ist_day_bounds
from app.utils.audit import log_action
import re
from app.models.consultation import Consultation
from app.models.patient import Patient
from app.models.admission import Admission
from app.models.checkin import Checkin
from sqlalchemy import func
from datetime import datetime, timedelta
from app.utils.ai_scribe_gate import get_ai_scribe_status, has_ai_scribe_at_all
from app.utils.billing_cycle import get_billing_cycle_info, is_renew_window_open, AI_SCRIBE_TOPUP_PRICING, AI_SCRIBE_TIER_CAPS
from app.models.suggestion import Suggestion
from app.models.ai_scribe_topup import AiScribeTopup
from app.models.upgrade_request import UpgradeRequest
from app.models.hospital_lead import HospitalLead
from app.models.plan_inquiry import PlanInquiry
from app.models.portal import PatientProfileLink
from app.models.audit_log import AuditLog
from dateutil.relativedelta import relativedelta

router = APIRouter(prefix="/admin", tags=["admin"])

def require_super_admin(current_doctor: Doctor):
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")


@router.get("/notifications-feed")
def get_notifications_feed(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Super admin's own notification feed — deliberately NOT the generic
    per-hospital Notification system (super admin has no hospital_id, so
    that system structurally can't apply). Aggregates exactly the things
    that are actually his to act on: new plan inquiries, hospital leads,
    upgrade requests, unseen suggestions, hospitals that have hit their
    tier's consultation limit, and hospitals whose billing cycle ends
    within 2 days. Each item's "unread" reflects its own real status field
    (or, for the two computed ones, is just always true — they're ongoing
    states with no dismiss action of their own yet)."""
    require_super_admin(current_doctor)
    now = now_ist_naive()
    items = []

    for pi in db.query(PlanInquiry).order_by(PlanInquiry.created_at.desc()).limit(50).all():
        items.append({
            "id": f"plan_inquiry-{pi.id}", "notif_type": "plan_inquiry", "severity": "info",
            "title": "New plan inquiry", "message": f"{pi.hospital_name} enquired about a plan.",
            "created_at": pi.created_at, "unread": pi.status == "new", "nav_section": "plan-inquiries",
        })

    for hl in db.query(HospitalLead).order_by(HospitalLead.created_at.desc()).limit(50).all():
        items.append({
            "id": f"hospital_lead-{hl.id}", "notif_type": "hospital_lead", "severity": "info",
            "title": "New hospital lead", "message": f"New lead: {hl.hospital_name}.",
            "created_at": hl.created_at, "unread": hl.status == "new", "nav_section": "hospital-leads",
        })

    for ur in db.query(UpgradeRequest).order_by(UpgradeRequest.created_at.desc()).limit(50).all():
        items.append({
            "id": f"upgrade_request-{ur.id}", "notif_type": "upgrade_request", "severity": "info",
            "title": "New upgrade request", "message": f"{ur.hospital_name} requested an upgrade.",
            "created_at": ur.created_at, "unread": ur.status == "new", "nav_section": "upgrade-requests",
        })

    for s in db.query(Suggestion).order_by(Suggestion.created_at.desc()).limit(50).all():
        items.append({
            "id": f"suggestion-{s.id}", "notif_type": "suggestion", "severity": "info",
            "title": "New suggestion", "message": f"New suggestion from {s.hospital_name}.",
            "created_at": s.created_at, "unread": s.status == "sent", "nav_section": "suggestions",
        })

    for h in db.query(Hospital).filter(Hospital.is_active == True).all():
        cap = AI_SCRIBE_TIER_CAPS.get(h.tier)
        if cap and h.ai_scribe_consultations_used >= cap:
            items.append({
                "id": f"hospital_limit-{h.id}", "notif_type": "hospital_limit", "severity": "warning",
                "title": "Hospital hit its consultation limit",
                "message": f"{h.name} has used {h.ai_scribe_consultations_used}/{cap} consultations on {h.tier.title()}.",
                "created_at": now, "unread": True, "nav_section": "hospitals", "hospital_id": h.id,
            })
        info = get_billing_cycle_info(h)
        if info and now < info["cycle_end"] and (info["cycle_end"] - now) <= timedelta(days=2):
            items.append({
                "id": f"billing_cycle-{h.id}", "notif_type": "billing_cycle", "severity": "warning",
                "title": "Billing cycle ending soon",
                "message": f"{h.name}'s billing cycle ends on {info['cycle_end'].strftime('%d %b, %Y')}.",
                "created_at": now, "unread": True, "nav_section": "hospitals", "hospital_id": h.id,
            })

    items.sort(key=lambda x: x["created_at"], reverse=True)
    for it in items:
        it["created_at"] = it["created_at"].isoformat()
    return {"notifications": items, "unread_count": sum(1 for it in items if it["unread"])}

@router.get("/upgrade-requests")
def list_upgrade_requests(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_super_admin(current_doctor)
    requests = db.query(UpgradeRequest).order_by(UpgradeRequest.created_at.desc()).all()
    result = []
    for r in requests:
        hospital = db.query(Hospital).filter(Hospital.id == r.hospital_id).first()
        result.append({
            "id": r.id,
            "hospital_id": r.hospital_id,
            "hospital_name": hospital.name if hospital else "Unknown",
            "requested_tier": r.requested_tier,
            "message": r.message,
            "contact_name": r.contact_name,
            "contact_phone": r.contact_phone,
            "contact_email": r.contact_email,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return result


@router.patch("/upgrade-requests/{request_id}/mark-contacted")
def mark_upgrade_request_contacted(
    request_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_super_admin(current_doctor)
    req = db.query(UpgradeRequest).filter(UpgradeRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    req.status = "contacted" if req.status == "new" else "new"
    db.commit()
    return {"id": req.id, "status": req.status}


@router.get("/hospital-leads")
def list_hospital_leads(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_super_admin(current_doctor)
    leads = db.query(HospitalLead).order_by(HospitalLead.created_at.desc()).all()
    result = []
    for l in leads:
        # "Requested By" needs a name, not just a phone number — resolved via
        # the account's EARLIEST linked patient profile (the one created at
        # signup, per PatientProfileLink's own docstring), so a family
        # account with multiple profiles always shows the main/first person,
        # not whichever profile happens to be most recent.
        main_link = (
            db.query(PatientProfileLink)
            .filter(PatientProfileLink.account_id == l.patient_account_id)
            .order_by(PatientProfileLink.id.asc())
            .first()
        )
        contact_name = main_link.patient.name if main_link and main_link.patient else None
        result.append({
            "id": l.id,
            "contact_name": contact_name,
            "contact_phone": l.contact_phone,
            "state": l.state,
            "city": l.city,
            "hospital_name": l.hospital_name,
            "location": l.location,
            "note": l.note,
            "status": l.status,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        })
    return result


@router.patch("/hospital-leads/{lead_id}/mark-contacted")
def mark_hospital_lead_contacted(
    lead_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_super_admin(current_doctor)
    lead = db.query(HospitalLead).filter(HospitalLead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead.status = "contacted" if lead.status == "new" else "new"
    db.commit()
    return {"id": lead.id, "status": lead.status}


@router.get("/plan-inquiries")
def list_plan_inquiries(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_super_admin(current_doctor)
    inquiries = db.query(PlanInquiry).order_by(PlanInquiry.created_at.desc()).all()
    return [
        {
            "id": i.id,
            "requested_tier": i.requested_tier,
            "billing_period": i.billing_period,
            "hospital_name": i.hospital_name,
            "contact_name": i.contact_name,
            "contact_phone": i.contact_phone,
            "contact_email": i.contact_email,
            "state": i.state,
            "city": i.city,
            "preferred_language": i.preferred_language,
            "message": i.message,
            "status": i.status,
            "created_at": i.created_at.isoformat() if i.created_at else None,
        }
        for i in inquiries
    ]


@router.patch("/plan-inquiries/{inquiry_id}/mark-contacted")
def mark_plan_inquiry_contacted(
    inquiry_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    require_super_admin(current_doctor)
    inquiry = db.query(PlanInquiry).filter(PlanInquiry.id == inquiry_id).first()
    if not inquiry:
        raise HTTPException(status_code=404, detail="Inquiry not found")
    inquiry.status = "contacted" if inquiry.status == "new" else "new"
    db.commit()
    return {"id": inquiry.id, "status": inquiry.status}


def serialize_billing_block(db: Session, hospital: Hospital) -> dict:
    """Shared by the hospital list and hospital detail endpoints so the two
    views can never disagree on used/total or renew-button state. Returns
    has_ai_scribe=False for Foundation with everything else null — per
    Praful, Foundation shows no topup/usage UI at all, not a 0/0 counter."""
    if not has_ai_scribe_at_all(hospital.tier):
        return {
            "has_ai_scribe": False,
            "ai_scribe_used": None, "ai_scribe_cap": None, "ai_scribe_topup_remaining": None, "ai_scribe_total_remaining": None,
            "billing_cycle_start": None, "billing_cycle_end": None, "grace_end": None, "deactivation_at": None,
            "renew_window_open": False,
        }

    status = get_ai_scribe_status(db, hospital)
    cycle = get_billing_cycle_info(hospital)
    now = now_ist_naive()

    return {
        "has_ai_scribe": True,
        "ai_scribe_used": status["used"],
        "ai_scribe_cap": status["cap"],  # None = unlimited (Enterprise) — frontend must show "Unlimited", not a fraction
        "ai_scribe_topup_remaining": status["topup_remaining"],
        "ai_scribe_total_remaining": status["total_remaining"],
        "billing_cycle_start": hospital.billing_cycle_start.isoformat() if hospital.billing_cycle_start else None,
        "billing_cycle_end": cycle["cycle_end"].isoformat() if cycle else None,
        "grace_end": cycle["grace_end"].isoformat() if cycle else None,
        "deactivation_at": cycle["deactivation_at"].isoformat() if cycle else None,
        "renew_window_open": is_renew_window_open(hospital, now),
    }

def verify_super_admin_key(x_super_admin_key: str = Header(...)):
    if x_super_admin_key != settings.SUPER_ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid super admin key")

def validate_fields(name, email, phone):
    # Password is no longer admin-supplied at creation — every new account
    # starts on settings.STAFF_DEFAULT_TEMP_PASSWORD and must set its own
    # via /auth/set-new-password on first login. Nothing left to validate here.
    if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
        raise HTTPException(status_code=400, detail="Invalid email format")
    if not re.match(r'^\+?[0-9]{10,13}$', phone):
        raise HTTPException(status_code=400, detail="Invalid phone number")
    if len(name.strip()) < 2:
        raise HTTPException(status_code=400, detail="Name too short")

VALID_HOSPITAL_TYPES = {"government", "private"}
VALID_TIERS = {"foundation", "growth", "scale", "enterprise"}

@router.post("/hospitals", status_code=201)
def create_hospital(
    name: str,
    city: str,
    state: str,
    address: str = "",
    hospital_type: str = "private",
    db: Session = Depends(get_db),
    _: None = Depends(verify_super_admin_key)
):
    hospital_type = hospital_type.strip().lower()
    if hospital_type not in VALID_HOSPITAL_TYPES:
        raise HTTPException(status_code=400, detail="hospital_type must be 'government' or 'private'")

    # Auto-generate hospital code from name
    words = name.strip().upper().split()
    code_base = "".join([w[0] for w in words])[:4]
    hospital_code = f"{code_base}-{secrets.token_hex(3).upper()}"

    # Ensure unique
    while db.query(Hospital).filter(Hospital.hospital_code == hospital_code).first():
        hospital_code = f"{code_base}-{secrets.token_hex(3).upper()}"

    hospital = Hospital(
        name=name,
        address=address,
        city=city,
        state=state,
        hospital_code=hospital_code,
        hospital_type=hospital_type,
        billing_enabled=(hospital_type == "private")
    )
    db.add(hospital)
    db.commit()
    db.refresh(hospital)
    return {"id": hospital.id, "name": hospital.name, "hospital_code": hospital.hospital_code, "hospital_type": hospital.hospital_type, "billing_enabled": hospital.billing_enabled}

@router.post("/create-admin", status_code=201)
def create_admin(
    hospital_id: int,
    name: str,
    email: str,
    phone: str,
    title: str = "Dr.",
    specialization: str = "General",
    db: Session = Depends(get_db),
    _: None = Depends(verify_super_admin_key)
):
    
    validate_fields(name, email, phone)

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    email = email.lower().strip()
    existing = db.query(Doctor).filter(Doctor.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    admin = Doctor(
        title=title,
        name=name,
        email=email,
        phone=phone,
        specialization=specialization,
        clinic_name=hospital.name,
        hashed_password=hash_password(settings.STAFF_DEFAULT_TEMP_PASSWORD),
        must_change_password=True,
        role=UserRole.admin,
        hospital_id=hospital_id,
        is_active=True
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return {
        "id": admin.id,
        "name": admin.name,
        "email": admin.email,
        "role": admin.role.value,
        "hospital": hospital.name,
        "hospital_code": hospital.hospital_code
    }

@router.get("/hospitals")
def list_hospitals(
    db: Session = Depends(get_db),
    _: None = Depends(verify_super_admin_key)
):
    hospitals = db.query(Hospital).all()
    return [{"id": h.id, "name": h.name, "hospital_code": h.hospital_code, "hospital_type": h.hospital_type, "city": h.city, "is_active": h.is_active} for h in hospitals]

def generate_doctor_uid(db: Session, hospital_code: str) -> str:
    import secrets, string
    prefix = (hospital_code or "STAF").replace("-", "")[:4].upper()
    alphabet = string.ascii_uppercase + string.digits
    while True:
        suffix = "".join(secrets.choice(alphabet) for _ in range(6))
        uid = f"{prefix}-{suffix}"
        if not db.query(Doctor).filter(Doctor.doctor_uid == uid).first():
            return uid


@router.post("/doctors", status_code=201)
def create_doctor(
    hospital_id: int,
    name: str,
    email: str,
    phone: str,
    specialization: str,
    title: str = "Dr.",
    registration_number: str = "",
    role: str = "doctor",
    room_number: str = "",
    consultation_fee: float = None,
    professional_fee_per_admission: float = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    # Only admin/sub_admin can create doctors
    if current_doctor.role.value not in ["admin", "sub_admin", "super_admin", "receptionist"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if role not in ["doctor", "sub_admin", "receptionist", "nurse", "assistant", "lab", "pharmacy", "radiology"]:
        raise HTTPException(status_code=400, detail="Invalid role")

    if current_doctor.role.value == "sub_admin" and role != "doctor":
        raise HTTPException(status_code=403, detail="Sub admin can only create doctor accounts")

    # Admin can only create doctors for their own hospital
    if current_doctor.role.value != "super_admin" and current_doctor.hospital_id != hospital_id:
        raise HTTPException(status_code=403, detail="Cannot create doctor for another hospital")

    validate_fields(name, email, phone)

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    email = email.lower().strip()
    existing = db.query(Doctor).filter(Doctor.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    doctor = Doctor(
        title=title,
        name=name,
        email=email,
        phone=phone,
        specialization=specialization,
        registration_number=registration_number,
        room_number=room_number or None,
        clinic_name=hospital.name,
        hashed_password=hash_password(settings.STAFF_DEFAULT_TEMP_PASSWORD),
        must_change_password=True,
        role=UserRole(role),
        hospital_id=hospital_id,
        is_active=True,
        created_by=current_doctor.id,
        consultation_fee=consultation_fee if role in ["doctor", "sub_admin"] else None,
        professional_fee_per_admission=professional_fee_per_admission if role in ["doctor", "sub_admin"] else None,
        doctor_uid=generate_doctor_uid(db, hospital.hospital_code),
    )
    db.add(doctor)
    db.commit()
    db.refresh(doctor)

    log_action(
        db, current_doctor,
        action="account_created",
        target_type="doctor",
        target_id=doctor.id,
        target_label=f"{doctor.title} {doctor.name}",
        details=f"Created as {doctor.role.value} in {hospital.name}"
    )

    return {
        "id": doctor.id,
        "name": doctor.name,
        "email": doctor.email,
        "role": doctor.role.value,
        "hospital": hospital.name
    }

@router.get("/billing/today")
def billing_today(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    from app.models.checkin import Checkin
    from app.models.medicine_order import MedicineOrder

    checkins = db.query(Checkin).filter(
        Checkin.hospital_id == current_doctor.hospital_id,
        Checkin.visit_date == ist_today()
    ).all()

    paid = [c for c in checkins if c.is_paid]
    unpaid = [c for c in checkins if not c.is_paid]

    total_collected = sum((c.consultation_fee or 0) + (c.test_fee or 0) for c in paid)
    total_unpaid = sum((c.consultation_fee or 0) + (c.test_fee or 0) for c in unpaid)

    today_start, today_end = ist_day_bounds()
    medicine_total = db.query(MedicineOrder).filter(
        MedicineOrder.hospital_id == current_doctor.hospital_id,
        MedicineOrder.status.in_(["paid", "dispensed"]),
        MedicineOrder.paid_at >= today_start,
        MedicineOrder.paid_at < today_end
    ).all()
    pharmacy_collected = sum((m.unit_price or 0) * ((m.billed_quantity if m.billed_quantity is not None else m.quantity) or 0) for m in medicine_total)

    return {
        "total_collected": total_collected + pharmacy_collected,
        "consultation_and_test_collected": total_collected,
        "pharmacy_collected": pharmacy_collected,
        "paid_count": len(paid),
        "unpaid_count": len(unpaid),
        "unpaid_amount": total_unpaid
    }

@router.patch("/hospital/fee-settings")
def update_fee_settings(
    default_consultation_fee: float,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    hospital = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    hospital.default_consultation_fee = default_consultation_fee
    db.commit()
    return {"default_consultation_fee": hospital.default_consultation_fee}


@router.get("/hospital/details")
def get_hospital_details(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    hospital = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    return {
        # Read-only — set by super admin only, tied to billing/plan tracking, never editable here
        "name": hospital.name,
        "hospital_code": hospital.hospital_code,
        "hospital_type": hospital.hospital_type,
        "city": hospital.city,
        "state": hospital.state,
        # Editable by hospital admin
        "address": hospital.address,
        "gstin": hospital.gstin,
        "phone": hospital.phone,
        "logo_base64": hospital.logo_base64,
        "default_consultation_fee": hospital.default_consultation_fee,
        "consultation_gst_percent": hospital.consultation_gst_percent,
        "test_gst_percent": hospital.test_gst_percent,
        "room_gst_percent": hospital.room_gst_percent,
        "charge_gst_percent": hospital.charge_gst_percent,
        "room_gst_threshold_per_day": hospital.room_gst_threshold_per_day,
        "waiver_auto_approve_cap": hospital.waiver_auto_approve_cap,
        "waiver_auto_approve_percent": hospital.waiver_auto_approve_percent,
        "hsn_consultation": hospital.hsn_consultation,
        "hsn_test": hospital.hsn_test,
        "hsn_room": hospital.hsn_room,
        "hsn_charge": hospital.hsn_charge
    }


class HospitalDetailsUpdate(BaseModel):
    address: Optional[str] = None
    gstin: Optional[str] = None
    phone: Optional[str] = None
    logo_base64: Optional[str] = None
    consultation_gst_percent: Optional[float] = None
    test_gst_percent: Optional[float] = None
    room_gst_percent: Optional[float] = None
    charge_gst_percent: Optional[float] = None
    room_gst_threshold_per_day: Optional[float] = None
    waiver_auto_approve_cap: Optional[float] = None
    waiver_auto_approve_percent: Optional[float] = None
    hsn_consultation: Optional[str] = None
    hsn_test: Optional[str] = None
    hsn_room: Optional[str] = None
    hsn_charge: Optional[str] = None
    # Deliberately no name/city/state/hospital_code/hospital_type here —
    # those are set once by super admin at hospital creation and tied to
    # billing/plan tracking. Admin cannot touch them even via direct API call.


@router.patch("/hospital/details")
def update_hospital_details(
    payload: HospitalDetailsUpdate,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    hospital = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    if payload.address is not None:
        hospital.address = payload.address.strip()
    if payload.gstin is not None:
        hospital.gstin = payload.gstin.strip() or None
    if payload.phone is not None:
        hospital.phone = payload.phone.strip() or None
    if payload.logo_base64 is not None:
        logo = payload.logo_base64.strip()
        if not logo:
            hospital.logo_base64 = None
        else:
            if not logo.startswith("data:image/"):
                raise HTTPException(status_code=400, detail="Logo must be an image upload")
            if len(logo) > 700_000:
                raise HTTPException(status_code=400, detail="Logo image is too large (max ~500KB)")
            hospital.logo_base64 = logo
    if payload.consultation_gst_percent is not None:
        hospital.consultation_gst_percent = payload.consultation_gst_percent or None
    if payload.test_gst_percent is not None:
        hospital.test_gst_percent = payload.test_gst_percent or None
    if payload.room_gst_percent is not None:
        hospital.room_gst_percent = payload.room_gst_percent or None
    if payload.charge_gst_percent is not None:
        hospital.charge_gst_percent = payload.charge_gst_percent or None
    if payload.room_gst_threshold_per_day is not None:
        hospital.room_gst_threshold_per_day = payload.room_gst_threshold_per_day
    if payload.waiver_auto_approve_cap is not None:
        hospital.waiver_auto_approve_cap = payload.waiver_auto_approve_cap or None
    if payload.waiver_auto_approve_percent is not None:
        hospital.waiver_auto_approve_percent = payload.waiver_auto_approve_percent or None
    if payload.hsn_consultation is not None:
        hospital.hsn_consultation = payload.hsn_consultation or None
    if payload.hsn_test is not None:
        hospital.hsn_test = payload.hsn_test or None
    if payload.hsn_room is not None:
        hospital.hsn_room = payload.hsn_room or None
    if payload.hsn_charge is not None:
        hospital.hsn_charge = payload.hsn_charge or None

    db.commit()
    return {
        "address": hospital.address,
        "gstin": hospital.gstin,
        "phone": hospital.phone,
        "logo_base64": hospital.logo_base64,
        "consultation_gst_percent": hospital.consultation_gst_percent,
        "test_gst_percent": hospital.test_gst_percent,
        "room_gst_percent": hospital.room_gst_percent,
        "charge_gst_percent": hospital.charge_gst_percent,
        "room_gst_threshold_per_day": hospital.room_gst_threshold_per_day,
        "waiver_auto_approve_cap": hospital.waiver_auto_approve_cap,
        "waiver_auto_approve_percent": hospital.waiver_auto_approve_percent,
        "hsn_consultation": hospital.hsn_consultation,
        "hsn_test": hospital.hsn_test,
        "hsn_room": hospital.hsn_room,
        "hsn_charge": hospital.hsn_charge
    }

ROOM_TYPE_PICKER_MAP = {"doctor": "Doctor", "nurse": "Nurse", "lab": "Lab"}

def serialize_room(r):
    return {
        "id": r.id,
        "room_number": r.room_number or "",
        "name": r.name or "",
        "room_type": r.room_type or "General",
        "type_confirmed": r.type_confirmed,
        "sequence_number": r.sequence_number,
        "display": f"{r.name or ''}{' (' + r.room_number + ')' if r.room_number else ''}".strip()
    }

def _make_room_slot(db, hospital_id, seq, exclude_room_id=None):
    """Free up sequence_number `seq` by shifting every active room at/after it up by one,
    so a new/moved room can drop into that slot (e.g. an inserted OPD room pushes the
    Emergency block after it down, keeping each type's numbers contiguous)."""
    from app.models.room import Room
    query = db.query(Room).filter(
        Room.hospital_id == hospital_id,
        Room.is_active == True,
        Room.sequence_number != None,
        Room.sequence_number >= seq
    )
    if exclude_room_id is not None:
        query = query.filter(Room.id != exclude_room_id)
    for r in query.order_by(Room.sequence_number.desc()).all():
        r.sequence_number += 1

@router.get("/rooms")
def list_rooms(
    for_picker: str = "",
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    from app.models.room import Room
    query = db.query(Room).filter(
        Room.hospital_id == current_doctor.hospital_id,
        Room.is_active == True
    )
    picker_type = ROOM_TYPE_PICKER_MAP.get(for_picker.strip().lower())
    if picker_type:
        # Doctor picker only shows Doctor-type rooms, nurse picker only Nurse-type —
        # General/Emergency/Other are deliberately excluded from both staff pickers.
        query = query.filter(Room.room_type == picker_type)
    rooms = query.all()
    return [serialize_room(r) for r in rooms]

@router.post("/rooms")
def create_room(
    room_number: str = "",
    name: str = "",
    room_type: str = "General",
    sequence_number: Optional[int] = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    if not room_number.strip() and not name.strip():
        raise HTTPException(status_code=400, detail="At least a room number or name is required")

    from app.models.room import Room
    if sequence_number is not None:
        if sequence_number < 1:
            raise HTTPException(status_code=400, detail="Sequence number must be positive")
        _make_room_slot(db, current_doctor.hospital_id, sequence_number)

    room = Room(
        hospital_id=current_doctor.hospital_id,
        room_number=room_number.strip() or None,
        name=name.strip() or None,
        room_type=room_type.strip() or "General",
        type_confirmed=True,
        is_active=True,
        sequence_number=sequence_number
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    return serialize_room(room)

@router.patch("/rooms/{room_id}")
def update_room_type(
    room_id: int,
    room_type: str = "",
    sequence_number: Optional[int] = None,
    clear_sequence_number: bool = False,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    if not room_type.strip():
        raise HTTPException(status_code=400, detail="Room type is required")

    from app.models.room import Room
    room = db.query(Room).filter(
        Room.id == room_id,
        Room.hospital_id == current_doctor.hospital_id
    ).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    if sequence_number is not None:
        if sequence_number < 1:
            raise HTTPException(status_code=400, detail="Sequence number must be positive")
        if room.sequence_number != sequence_number:
            _make_room_slot(db, current_doctor.hospital_id, sequence_number, exclude_room_id=room.id)
            room.sequence_number = sequence_number
    elif clear_sequence_number:
        room.sequence_number = None

    room.room_type = room_type.strip()
    room.type_confirmed = True
    db.commit()
    db.refresh(room)
    return serialize_room(room)

@router.delete("/rooms/{room_id}")
def delete_room(
    room_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    from app.models.room import Room
    room = db.query(Room).filter(
        Room.id == room_id,
        Room.hospital_id == current_doctor.hospital_id
    ).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    room.is_active = False
    db.commit()
    return {"deleted": True}

@router.get("/doctors")
def list_doctors(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    doctors_query = db.query(Doctor).filter(
        Doctor.role.in_([UserRole.doctor, UserRole.sub_admin, UserRole.receptionist, UserRole.nurse, UserRole.assistant, UserRole.lab, UserRole.pharmacy, UserRole.radiology])
    )
    if current_doctor.role.value != "super_admin":
        doctors_query = doctors_query.filter(Doctor.hospital_id == current_doctor.hospital_id)
    doctors = doctors_query.all()

    now = now_ist_naive()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)

    from app.models.checkin import Checkin

    result = []
    for d in doctors:
        if d.role.value in ("nurse", "assistant"):
            total = db.query(Checkin).filter(Checkin.vitals_recorded_by == d.id).count()
            today = db.query(Checkin).filter(Checkin.vitals_recorded_by == d.id, Checkin.vitals_recorded_at >= today_start).count()
            week = db.query(Checkin).filter(Checkin.vitals_recorded_by == d.id, Checkin.vitals_recorded_at >= week_start).count()
        elif d.role.value == "receptionist":
            total = db.query(Checkin).filter(Checkin.created_by == d.id).count()
            today = db.query(Checkin).filter(Checkin.created_by == d.id, Checkin.created_at >= today_start).count()
            week = db.query(Checkin).filter(Checkin.created_by == d.id, Checkin.created_at >= week_start).count()
        else:
            total = db.query(Consultation).filter(
                Consultation.doctor_id == d.id,
                Consultation.token_number != None,
                Consultation.is_voided == False
            ).count()
            today = db.query(Consultation).filter(
                Consultation.doctor_id == d.id,
                Consultation.token_number != None,
                Consultation.is_voided == False,
                Consultation.created_at >= today_start
            ).count()
            week = db.query(Consultation).filter(
                Consultation.doctor_id == d.id,
                Consultation.token_number != None,
                Consultation.is_voided == False,
                Consultation.created_at >= week_start
            ).count()
        result.append({
            "id": d.id,
            "name": d.name,
            "title": d.title,
            "email": d.email,
            "phone": d.phone,
            "specialization": d.specialization,
            "registration_number": d.registration_number or "",
            "is_active": d.is_active,
            "role": d.role.value,
            "is_hiv_authorized": d.is_hiv_authorized,
            "consultation_fee": d.consultation_fee,
            "professional_fee_per_admission": d.professional_fee_per_admission,
            "consultations_today": today,
            "consultations_week": week,
            "consultations_total": total
        })
    return result

@router.patch("/doctors/{doctor_id}/toggle-active")
def toggle_doctor_active(
    doctor_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    doctor_query = db.query(Doctor).filter(Doctor.id == doctor_id)
    if current_doctor.role.value != "super_admin":
        doctor_query = doctor_query.filter(Doctor.hospital_id == current_doctor.hospital_id)
    doctor = doctor_query.first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    # Prevent deactivating yourself
    if doctor.id == current_doctor.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")

    # sub_admin cannot deactivate admin or other sub_admins
    if current_doctor.role.value == "sub_admin" and doctor.role.value in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Sub admin cannot deactivate admin accounts")

    # admin cannot deactivate other admins or sub_admins
    if current_doctor.role.value == "admin" and doctor.role.value in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Cannot deactivate admin or sub admin accounts")

    doctor.is_active = not doctor.is_active
    db.commit()

    log_action(
        db, current_doctor,
        action="account_activated" if doctor.is_active else "account_deactivated",
        target_type="doctor",
        target_id=doctor.id,
        target_label=f"{doctor.title} {doctor.name}"
    )

    return {"id": doctor.id, "is_active": doctor.is_active}


@router.patch("/doctors/{doctor_id}/toggle-hiv-authorized")
def toggle_hiv_authorized(
    doctor_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Explicit, per-person grant — tighter than the general 'lab' role
    for HIV result access (Phase 6 item 21)."""
    if current_doctor.role.value not in ["admin", "sub_admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    doctor_query = db.query(Doctor).filter(Doctor.id == doctor_id)
    if current_doctor.role.value != "super_admin":
        doctor_query = doctor_query.filter(Doctor.hospital_id == current_doctor.hospital_id)
    doctor = doctor_query.first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    if doctor.role.value != "lab":
        raise HTTPException(status_code=400, detail="Only lab-role staff can be granted HIV authorization")

    doctor.is_hiv_authorized = not doctor.is_hiv_authorized
    db.commit()

    log_action(
        db, current_doctor,
        action="hiv_authorization_granted" if doctor.is_hiv_authorized else "hiv_authorization_revoked",
        target_type="doctor", target_id=doctor.id, target_label=f"{doctor.title} {doctor.name}"
    )
    return {"id": doctor.id, "is_hiv_authorized": doctor.is_hiv_authorized}


@router.patch("/doctors/{doctor_id}/toggle-role")
def toggle_doctor_role(
    doctor_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Only admin or super admin can change roles")

    doctor_query = db.query(Doctor).filter(Doctor.id == doctor_id)
    if current_doctor.role.value != "super_admin":
        doctor_query = doctor_query.filter(Doctor.hospital_id == current_doctor.hospital_id)
    doctor = doctor_query.first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    if doctor.id == current_doctor.id:
        raise HTTPException(status_code=400, detail="You cannot change your own role")

    if doctor.role.value not in ["doctor", "sub_admin"]:
        raise HTTPException(status_code=400, detail="Can only toggle role between doctor and sub admin")

    old_role = doctor.role.value
    doctor.role = UserRole.doctor if doctor.role.value == "sub_admin" else UserRole.sub_admin
    db.commit()

    log_action(
        db, current_doctor,
        action="role_changed",
        target_type="doctor",
        target_id=doctor.id,
        target_label=f"{doctor.title} {doctor.name}",
        details=f"{old_role} → {doctor.role.value}"
    )

    return {"id": doctor.id, "role": doctor.role.value}

@router.patch("/doctors/{doctor_id}/toggle-nurse-assistant")
def toggle_nurse_assistant_role(
    doctor_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Only admin or super admin can change roles")

    doctor_query = db.query(Doctor).filter(Doctor.id == doctor_id)
    if current_doctor.role.value != "super_admin":
        doctor_query = doctor_query.filter(Doctor.hospital_id == current_doctor.hospital_id)
    doctor = doctor_query.first()

    if not doctor:
        raise HTTPException(status_code=404, detail="Staff member not found")

    if doctor.id == current_doctor.id:
        raise HTTPException(status_code=400, detail="You cannot change your own role")

    if doctor.role.value not in ["nurse", "assistant"]:
        raise HTTPException(status_code=400, detail="Can only toggle role between nurse and assistant")

    old_role = doctor.role.value
    doctor.role = UserRole.assistant if doctor.role.value == "nurse" else UserRole.nurse
    db.commit()

    log_action(
        db, current_doctor,
        action="role_changed",
        target_type="doctor",
        target_id=doctor.id,
        target_label=f"{doctor.title} {doctor.name}",
        details=f"{old_role} → {doctor.role.value}"
    )

    return {"id": doctor.id, "role": doctor.role.value}

@router.post("/create-superadmin", status_code=201)
def create_superadmin(
    name: str,
    email: str,
    phone: str,
    password: str,
    db: Session = Depends(get_db),
    _: None = Depends(verify_super_admin_key)
):
    email = email.lower().strip()
    existing = db.query(Doctor).filter(Doctor.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    superadmin = Doctor(
        title="",
        name=name,
        email=email,
        phone=phone,
        specialization="",
        clinic_name="",
        hashed_password=hash_password(password),
        role=UserRole.super_admin,
        hospital_id=None,
        is_active=True
    )
    db.add(superadmin)
    db.commit()
    db.refresh(superadmin)
    return {
        "id": superadmin.id,
        "name": superadmin.name,
        "email": superadmin.email,
        "role": superadmin.role.value
    }

@router.post("/create-subadmin", status_code=201)
def create_subadmin(
    hospital_id: int,
    name: str,
    email: str,
    phone: str,
    specialization: str = "",
    title: str = "Dr.",
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    if current_doctor.role.value != "super_admin" and current_doctor.hospital_id != hospital_id:
        raise HTTPException(status_code=403, detail="Cannot create sub admin for another hospital")

    validate_fields(name, email, phone)

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    email = email.lower().strip()
    existing = db.query(Doctor).filter(Doctor.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    subadmin = Doctor(
        title=title,
        name=name,
        email=email,
        phone=phone,
        specialization=specialization,
        clinic_name=hospital.name,
        hashed_password=hash_password(settings.STAFF_DEFAULT_TEMP_PASSWORD),
        must_change_password=True,
        role=UserRole.sub_admin,
        hospital_id=hospital_id,
        is_active=True,
        created_by=current_doctor.id
    )
    db.add(subadmin)
    db.commit()
    db.refresh(subadmin)
    return {
        "id": subadmin.id,
        "name": subadmin.name,
        "email": subadmin.email,
        "role": subadmin.role.value,
        "hospital": hospital.name
    }

@router.get("/hospitals-list")
def list_hospitals_jwt(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    
    hospitals = db.query(Hospital).all()
    return [
        {
            "id": h.id,
            "name": h.name,
            "hospital_code": h.hospital_code,
            "hospital_type": h.hospital_type,
            "billing_enabled": h.billing_enabled,
            "tier": h.tier,
            "city": h.city,
            "is_active": h.is_active,
            **serialize_billing_block(db, h),
        }
        for h in hospitals
    ]

@router.patch("/hospitals/{hospital_id}/billing-cycle-start")
def set_hospital_billing_cycle_start(
    hospital_id: int,
    cycle_start_date: str,  # "YYYY-MM-DD" — super admin enters this manually (item 4/6), not derived from any login event
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    try:
        parsed = datetime.strptime(cycle_start_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="cycle_start_date must be YYYY-MM-DD")

    hospital.billing_cycle_start = parsed
    hospital.ai_scribe_consultations_used = 0  # setting/resetting the anchor starts a fresh cycle
    db.commit()

    log_action(
        db, current_doctor,
        action="hospital_billing_cycle_start_set",
        target_type="hospital",
        target_id=hospital.id,
        target_label=hospital.name,
        details=f"Billing cycle start set to {cycle_start_date}",
        hospital_id=hospital.id
    )

    return {"id": hospital.id, "billing_cycle_start": hospital.billing_cycle_start.isoformat()}


@router.post("/hospitals/{hospital_id}/ai-scribe-topup", status_code=201)
def buy_ai_scribe_topup(
    hospital_id: int,
    block_size: int,
    payment_collected: bool,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Item 3. The confirmation popup asking whether payment was collected
    lives in the frontend, before this call ever fires — payment_collected
    is sent as part of that confirmation, and this endpoint refuses to
    create anything unless it's explicitly True, so a topup can never be
    granted without that confirmation having happened."""
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    if block_size not in AI_SCRIBE_TOPUP_PRICING:
        raise HTTPException(status_code=400, detail=f"block_size must be one of {sorted(AI_SCRIBE_TOPUP_PRICING.keys())}")
    if not payment_collected:
        raise HTTPException(status_code=400, detail="Payment must be confirmed as collected before a topup can be applied")

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    if not hospital.is_active:
        raise HTTPException(status_code=400, detail="This hospital is deactivated — a topup would sit unused. Reactivate first.")
    if not has_ai_scribe_at_all(hospital.tier):
        raise HTTPException(status_code=400, detail="This hospital's tier doesn't include AI Scribe — a topup wouldn't be usable")

    now = now_ist_naive()
    topup = AiScribeTopup(
        hospital_id=hospital.id,
        block_size=block_size,
        consultations_granted=block_size,
        price_paid=AI_SCRIBE_TOPUP_PRICING[block_size],
        payment_collected=True,
        purchased_at=now,
        expires_at=now + timedelta(days=30),
        purchased_by=current_doctor.id,
    )
    db.add(topup)
    db.commit()
    db.refresh(topup)

    log_action(
        db, current_doctor,
        action="ai_scribe_topup_purchased",
        target_type="hospital",
        target_id=hospital.id,
        target_label=hospital.name,
        details=f"{block_size} consultations for Rs.{topup.price_paid}, expires {topup.expires_at.date().isoformat()}",
        hospital_id=hospital.id
    )

    return {"id": topup.id, "hospital_id": hospital.id, "block_size": block_size, "price_paid": topup.price_paid, "expires_at": topup.expires_at.isoformat()}


@router.post("/hospitals/{hospital_id}/renew")
def renew_hospital_billing_cycle(
    hospital_id: int,
    confirm: bool,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Item 6. Same pattern as the topup endpoint — the payment-collected
    confirmation popup lives in the frontend, confirm=True is what it sends
    after that popup, and this refuses to do anything without it. The
    button being enabled client-side (2-day-before through grace-end) is
    mirrored here server-side so a stale/forced request can't renew outside
    that window either."""
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    if not confirm:
        raise HTTPException(status_code=400, detail="Payment must be confirmed before renewing")

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    if not hospital.is_active:
        raise HTTPException(status_code=400, detail="This hospital is deactivated — use Activate, not Renew, to bring it back")
    if not hospital.billing_cycle_start:
        raise HTTPException(status_code=400, detail="No billing cycle has been set for this hospital yet")

    now = now_ist_naive()
    if not is_renew_window_open(hospital, now):
        raise HTTPException(status_code=400, detail="It's not yet time to renew this hospital — the Renew window opens 2 days before cycle-end")

    # Stays anchored to the ORIGINAL cycle_start's day-of-month — advances
    # by exactly one month from the current anchor, not from "now" (item 6:
    # "cycle stays anchored to the original signup date, not the date the
    # button was pressed").
    hospital.billing_cycle_start = hospital.billing_cycle_start + relativedelta(months=1)
    hospital.ai_scribe_consultations_used = 0
    db.commit()

    log_action(
        db, current_doctor,
        action="hospital_billing_cycle_renewed",
        target_type="hospital",
        target_id=hospital.id,
        target_label=hospital.name,
        details=f"New cycle: {hospital.billing_cycle_start.date().isoformat()}",
        hospital_id=hospital.id
    )

    return {"id": hospital.id, "billing_cycle_start": hospital.billing_cycle_start.isoformat()}


@router.patch("/hospitals/{hospital_id}/tier")
def set_hospital_tier(
    hospital_id: int,
    tier: str,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    tier = tier.strip().lower()
    if tier not in VALID_TIERS:
        raise HTTPException(status_code=400, detail=f"tier must be one of {sorted(VALID_TIERS)}")

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    previous_tier = hospital.tier
    hospital.tier = tier
    db.commit()

    log_action(
        db, current_doctor,
        action="hospital_tier_changed",
        target_type="hospital",
        target_id=hospital.id,
        target_label=hospital.name,
        details=f"Tier changed from {previous_tier} to {tier}",
        hospital_id=hospital.id
    )

    return {"id": hospital.id, "tier": hospital.tier}

@router.patch("/hospitals/{hospital_id}/toggle-billing")
def toggle_hospital_billing(
    hospital_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    hospital.billing_enabled = not hospital.billing_enabled
    db.commit()

    log_action(
        db, current_doctor,
        action="billing_enabled_toggled",
        target_type="hospital",
        target_id=hospital.id,
        target_label=hospital.name,
        details=f"Billing {'enabled' if hospital.billing_enabled else 'disabled'}",
        hospital_id=hospital.id
    )

    return {"id": hospital.id, "billing_enabled": hospital.billing_enabled}

@router.patch("/hospitals/{hospital_id}/toggle-active")
def toggle_hospital_active(
    hospital_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    was_active = hospital.is_active
    hospital.is_active = not hospital.is_active

    reanchored = False
    if not was_active and hospital.is_active and hospital.billing_cycle_start:
        # Item 7: reactivating after a deactivation re-anchors the billing
        # cycle to today, not the original signup date — only when a cycle
        # was already running; a hospital that never had one set stays None
        # until the super admin sets it manually.
        hospital.billing_cycle_start = now_ist_naive()
        hospital.ai_scribe_consultations_used = 0
        reanchored = True

    db.commit()

    log_action(
        db, current_doctor,
        action="hospital_activated" if hospital.is_active else "hospital_deactivated",
        target_type="hospital",
        target_id=hospital.id,
        target_label=hospital.name,
        details="Billing cycle re-anchored to reactivation date" if reanchored else None,
        hospital_id=hospital.id
    )

    return {"id": hospital.id, "is_active": hospital.is_active, "billing_cycle_start": hospital.billing_cycle_start.isoformat() if hospital.billing_cycle_start else None}

@router.post("/hospitals-jwt", status_code=201)
def create_hospital_jwt(
    name: str,
    city: str,
    state: str,
    address: str = "",
    hospital_type: str = "private",
    tier: str = "growth",
    billing_cycle_start: str = None,  # "YYYY-MM-DD" — required, asked at creation time now instead of set separately after the fact
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    hospital_type = hospital_type.strip().lower()
    if hospital_type not in VALID_HOSPITAL_TYPES:
        raise HTTPException(status_code=400, detail="hospital_type must be 'government' or 'private'")

    tier = tier.strip().lower()
    if tier not in VALID_TIERS:
        raise HTTPException(status_code=400, detail=f"tier must be one of {sorted(VALID_TIERS)}")

    if not billing_cycle_start:
        raise HTTPException(status_code=400, detail="billing_cycle_start is required")
    try:
        parsed_cycle_start = datetime.strptime(billing_cycle_start, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="billing_cycle_start must be YYYY-MM-DD")

    words = name.strip().upper().split()
    code_base = "".join([w[0] for w in words])[:4]
    hospital_code = f"{code_base}-{secrets.token_hex(3).upper()}"
    while db.query(Hospital).filter(Hospital.hospital_code == hospital_code).first():
        hospital_code = f"{code_base}-{secrets.token_hex(3).upper()}"

    hospital = Hospital(
        name=name, address=address, city=city, state=state, hospital_code=hospital_code,
        hospital_type=hospital_type, billing_enabled=(hospital_type == "private"),
        tier=tier, billing_cycle_start=parsed_cycle_start,
    )
    db.add(hospital)
    db.commit()
    db.refresh(hospital)

    log_action(
        db, current_doctor,
        action="hospital_created",
        target_type="hospital",
        target_id=hospital.id,
        target_label=hospital.name,
        hospital_id=hospital.id
    )
    return {"id": hospital.id, "name": hospital.name, "hospital_code": hospital.hospital_code, "hospital_type": hospital.hospital_type, "billing_enabled": hospital.billing_enabled}

@router.post("/create-admin-jwt", status_code=201)
def create_admin_jwt(
    hospital_id: int,
    name: str,
    email: str,
    phone: str,
    specialization: str,
    title: str = "Dr.",
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    validate_fields(name, email, phone)

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    email = email.lower().strip()
    existing = db.query(Doctor).filter(Doctor.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    admin = Doctor(
        title=title, name=name, email=email, phone=phone,
        specialization=specialization, clinic_name=hospital.name,
        hashed_password=hash_password(settings.STAFF_DEFAULT_TEMP_PASSWORD),
        must_change_password=True,
        role=UserRole.admin, hospital_id=hospital_id, is_active=True
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)

    log_action(
        db, current_doctor,
        action="account_created",
        target_type="doctor",
        target_id=admin.id,
        target_label=f"{admin.title} {admin.name}",
        details=f"Created as admin in {hospital.name}",
        hospital_id=hospital_id
    )

    return {"id": admin.id, "name": admin.name, "email": admin.email, "role": admin.role.value}

@router.get("/stats")
def superadmin_stats(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    month_start = now_ist_naive().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    active_hospitals = db.query(Hospital).filter(Hospital.is_active == True).all()
    total_hospitals = len(active_hospitals)
    new_hospitals_this_month = db.query(Hospital).filter(
        Hospital.created_at >= month_start
    ).count()

    from app.utils.billing_cycle import TIER_MONTHLY_PRICE
    monthly_revenue = sum(TIER_MONTHLY_PRICE.get(h.tier, 0) for h in active_hospitals)

    hospitals_by_tier = {"foundation": 0, "growth": 0, "scale": 0, "enterprise": 0}
    for h in active_hospitals:
        if h.tier in hospitals_by_tier:
            hospitals_by_tier[h.tier] += 1

    return {
        "total_hospitals": total_hospitals,
        "new_hospitals_this_month": new_hospitals_this_month,
        "monthly_revenue": monthly_revenue,
        "hospitals_by_tier": hospitals_by_tier,
    }

@router.get("/analytics/platform/growth")
def platform_growth_analytics(
    trend_interval: str = "monthly",
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Phase 1 — Hospital & growth metrics for the platform-wide Analytics
    tab. Hospital count is small (tens/hundreds of rows), so bucketing is
    done in Python off one query rather than N date-truncated SQL queries —
    revisit if hospital count ever gets large. Patient/consultation-volume
    metrics (later phases) must NOT follow this pattern; those need
    DB-level aggregation."""
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    if trend_interval not in ("monthly", "weekly"):
        raise HTTPException(status_code=400, detail="trend_interval must be 'monthly' or 'weekly'")

    now = now_ist_naive()
    TIER_ORDER = ["foundation", "growth", "scale", "enterprise"]
    TIER_RANK = {t: i for i, t in enumerate(TIER_ORDER)}

    all_hospitals = db.query(Hospital).all()
    total_hospitals = len(all_hospitals)

    by_tier = {t: 0 for t in TIER_ORDER}
    for h in all_hospitals:
        if h.tier in by_tier:
            by_tier[h.tier] += 1

    active_hospitals = [h for h in all_hospitals if h.is_active]
    deactivated_count = total_hospitals - len(active_hospitals)

    grace_period_count = 0
    for h in active_hospitals:
        info = get_billing_cycle_info(h)
        if info and info["cycle_end"] <= now < info["deactivation_at"]:
            grace_period_count += 1

    # ── Build bucket boundaries (12 buckets, monthly or weekly) ──
    bucket_count = 12
    if trend_interval == "monthly":
        period_start = (now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                         - relativedelta(months=bucket_count - 1))
        bucket_starts = [period_start + relativedelta(months=i) for i in range(bucket_count)]
        bucket_ends = [b + relativedelta(months=1) for b in bucket_starts]
        period_labels = [b.strftime("%Y-%m") for b in bucket_starts]
    else:
        this_monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        period_start = this_monday - timedelta(weeks=bucket_count - 1)
        bucket_starts = [period_start + timedelta(weeks=i) for i in range(bucket_count)]
        bucket_ends = [b + timedelta(weeks=1) for b in bucket_starts]
        period_labels = [b.strftime("%Y-%m-%d") for b in bucket_starts]

    onboarding_trend = []
    for label, b_start, b_end in zip(period_labels, bucket_starts, bucket_ends):
        count = sum(1 for h in all_hospitals if b_start <= h.created_at < b_end)
        onboarding_trend.append({"period": label, "count": count})

    # ── Tier upgrade/downgrade movements, parsed from AuditLog ──
    tier_change_logs = db.query(AuditLog).filter(
        AuditLog.action == "hospital_tier_changed",
        AuditLog.created_at >= period_start
    ).all()

    tier_buckets = {label: {"upgrades": 0, "downgrades": 0} for label in period_labels}
    tier_change_total = {"upgrades": 0, "downgrades": 0}
    for log in tier_change_logs:
        m = re.match(r"Tier changed from (\w+) to (\w+)", log.details or "")
        if not m:
            continue
        from_tier, to_tier = m.group(1), m.group(2)
        if from_tier not in TIER_RANK or to_tier not in TIER_RANK:
            continue
        direction = "upgrades" if TIER_RANK[to_tier] > TIER_RANK[from_tier] else "downgrades"
        if trend_interval == "monthly":
            label = log.created_at.replace(day=1).strftime("%Y-%m")
        else:
            log_monday = log.created_at - timedelta(days=log.created_at.weekday())
            label = log_monday.strftime("%Y-%m-%d")
        if label in tier_buckets:
            tier_buckets[label][direction] += 1
        tier_change_total[direction] += 1

    tier_change_trend = [
        {"period": label, "upgrades": tier_buckets[label]["upgrades"], "downgrades": tier_buckets[label]["downgrades"]}
        for label in period_labels
    ]

    # ── Geographic distribution ──
    geo_counts = {}
    for h in all_hospitals:
        key = (h.state or "Unknown", h.city or "Unknown")
        geo_counts[key] = geo_counts.get(key, 0) + 1
    geographic_distribution = [
        {"state": state, "city": city, "count": count}
        for (state, city), count in sorted(geo_counts.items(), key=lambda x: -x[1])
    ]

    return {
        "trend_interval": trend_interval,
        "total_hospitals": total_hospitals,
        "by_tier": by_tier,
        "active_count": len(active_hospitals),
        "deactivated_count": deactivated_count,
        "grace_period_count": grace_period_count,
        "onboarding_trend": onboarding_trend,
        "tier_change_trend": tier_change_trend,
        "tier_change_total": tier_change_total,
        "geographic_distribution": geographic_distribution,
    }

@router.get("/analytics/platform/patients-usage")
def platform_patients_usage_analytics(
    trend_interval: str = "monthly",
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Phase 1 — Patient & usage metrics, platform-wide. Average consultation
    duration is deliberately NOT included: Consultation only stores
    created_at, no start/confirm timestamp pair exists to compute a
    duration from. Flagging again rather than guessing — let me know if
    you want a started_at-style column added before this metric gets built.

    Trends use DB-level GROUP BY date_trunc(), not Python loops over rows —
    patient/consultation/admission volume can get large, unlike hospital
    counts."""
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    if trend_interval not in ("monthly", "weekly"):
        raise HTTPException(status_code=400, detail="trend_interval must be 'monthly' or 'weekly'")

    now = now_ist_naive()
    bucket_count = 12
    trunc_unit = "month" if trend_interval == "monthly" else "week"

    if trend_interval == "monthly":
        period_start = (now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                         - relativedelta(months=bucket_count - 1))
        bucket_starts = [period_start + relativedelta(months=i) for i in range(bucket_count)]
        period_labels = [b.strftime("%Y-%m") for b in bucket_starts]
        fmt = "%Y-%m"
    else:
        this_monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        period_start = this_monday - timedelta(weeks=bucket_count - 1)
        bucket_starts = [period_start + timedelta(weeks=i) for i in range(bucket_count)]
        period_labels = [b.strftime("%Y-%m-%d") for b in bucket_starts]
        fmt = "%Y-%m-%d"

    def _trend_from(model, date_col):
        rows = (
            db.query(func.date_trunc(trunc_unit, date_col).label("bucket"), func.count(model.id))
            .filter(date_col >= period_start)
            .group_by("bucket")
            .all()
        )
        counted = {r[0].strftime(fmt): r[1] for r in rows if r[0] is not None}
        return [{"period": label, "count": counted.get(label, 0)} for label in period_labels]

    total_patients = db.query(func.count(Patient.id)).scalar() or 0
    portal_activated = db.query(func.count(func.distinct(PatientProfileLink.patient_id))).scalar() or 0

    total_consultations = db.query(func.count(Consultation.id)).scalar() or 0
    consultation_trend = _trend_from(Consultation, Consultation.created_at)

    total_admissions = db.query(func.count(Admission.id)).scalar() or 0
    admission_trend = _trend_from(Admission, Admission.admission_date)

    online_count = db.query(func.count(Checkin.id)).filter(Checkin.source == "online").scalar() or 0
    walkin_count = db.query(func.count(Checkin.id)).filter(Checkin.source == "walk_in").scalar() or 0

    return {
        "trend_interval": trend_interval,
        "total_patients": total_patients,
        "portal_activated_patients": portal_activated,
        "portal_adoption_rate": round((portal_activated / total_patients) * 100, 1) if total_patients else 0,
        "total_opd_consultations": total_consultations,
        "opd_consultation_trend": consultation_trend,
        "total_ipd_admissions": total_admissions,
        "ipd_admission_trend": admission_trend,
        "online_bookings": online_count,
        "walk_in_registrations": walkin_count,
        "average_consultation_duration": None,
    }

@router.get("/analytics/platform/ai-scribe")
def platform_ai_scribe_analytics(
    trend_interval: str = "monthly",
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Phase 1 — AI Scribe / business-critical usage metrics, platform-wide.

    current_cycle_tier_usage is NOT an all-time total — Hospital.ai_scribe_
    consultations_used resets on every renewal, so this is a snapshot of
    the current cycle only, labeled as such. all_time_topup_usage IS
    genuinely cumulative (topup rows are never reset). Enterprise-tier
    hospitals are excluded from usage totals entirely — consume_ai_scribe_
    credit() never increments any counter for unlimited tiers, so there's
    nothing to sum for them."""
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    if trend_interval not in ("monthly", "weekly"):
        raise HTTPException(status_code=400, detail="trend_interval must be 'monthly' or 'weekly'")

    now = now_ist_naive()
    bucket_count = 12
    trunc_unit = "month" if trend_interval == "monthly" else "week"

    if trend_interval == "monthly":
        period_start = (now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                         - relativedelta(months=bucket_count - 1))
        bucket_starts = [period_start + relativedelta(months=i) for i in range(bucket_count)]
        period_labels = [b.strftime("%Y-%m") for b in bucket_starts]
        fmt = "%Y-%m"
    else:
        this_monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        period_start = this_monday - timedelta(weeks=bucket_count - 1)
        bucket_starts = [period_start + timedelta(weeks=i) for i in range(bucket_count)]
        period_labels = [b.strftime("%Y-%m-%d") for b in bucket_starts]
        fmt = "%Y-%m-%d"

    eligible_hospitals = [
        h for h in db.query(Hospital).filter(Hospital.is_active == True).all()
        if has_ai_scribe_at_all(h.tier)
    ]

    current_cycle_tier_usage = sum(h.ai_scribe_consultations_used for h in eligible_hospitals)
    average_usage_per_hospital = round(current_cycle_tier_usage / len(eligible_hospitals), 1) if eligible_hospitals else 0

    all_time_topup_usage = db.query(func.sum(AiScribeTopup.consultations_used)).scalar() or 0

    approaching_or_at_cap = []
    for h in eligible_hospitals:
        cap = AI_SCRIBE_TIER_CAPS.get(h.tier)
        if not cap:  # unlimited (Enterprise) or 0 — nothing meaningful to flag
            continue
        pct = (h.ai_scribe_consultations_used / cap) * 100
        if pct >= 80:
            status_info = get_ai_scribe_status(db, h)
            approaching_or_at_cap.append({
                "hospital_id": h.id,
                "hospital_name": h.name,
                "tier": h.tier,
                "used": h.ai_scribe_consultations_used,
                "cap": cap,
                "percent_used": round(pct, 1),
                "topup_remaining": status_info["topup_remaining"],
                "status": "at_cap" if pct >= 100 else "approaching",
            })
    approaching_or_at_cap.sort(key=lambda x: -x["percent_used"])

    total_topup_count = db.query(func.count(AiScribeTopup.id)).scalar() or 0
    total_topup_revenue = db.query(func.sum(AiScribeTopup.price_paid)).filter(
        AiScribeTopup.payment_collected == True
    ).scalar() or 0

    topup_rows = (
        db.query(
            func.date_trunc(trunc_unit, AiScribeTopup.purchased_at).label("bucket"),
            func.count(AiScribeTopup.id),
            func.sum(AiScribeTopup.price_paid),
        )
        .filter(AiScribeTopup.purchased_at >= period_start, AiScribeTopup.payment_collected == True)
        .group_by("bucket")
        .all()
    )
    topup_bucketed = {r[0].strftime(fmt): {"count": r[1], "revenue": r[2] or 0} for r in topup_rows if r[0] is not None}
    topup_trend = [
        {"period": label, "count": topup_bucketed.get(label, {}).get("count", 0), "revenue": topup_bucketed.get(label, {}).get("revenue", 0)}
        for label in period_labels
    ]

    return {
        "trend_interval": trend_interval,
        "current_cycle_tier_usage": current_cycle_tier_usage,
        "average_usage_per_hospital": average_usage_per_hospital,
        "all_time_topup_usage": all_time_topup_usage,
        "eligible_hospital_count": len(eligible_hospitals),
        "approaching_or_at_cap": approaching_or_at_cap,
        "total_topup_count": total_topup_count,
        "total_topup_revenue": total_topup_revenue,
        "topup_trend": topup_trend,
    }

@router.get("/analytics/platform/business")
def platform_business_analytics(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Phase 1 — Business/revenue metrics, platform-wide.

    Hospital Leads -> onboarded-hospital conversion rate is deliberately
    NOT included: HospitalLead has no link to the Hospital it may have
    become, only a free-text name, and name-matching would be a guess, not
    real data. Flagging rather than building an unreliable number — a
    converted_hospital_id column would fix this properly, see chat.

    Upgrade-request conversion IS computed for real: checks, for each
    UpgradeRequest, whether a later hospital_tier_changed AuditLog exists
    for that hospital landing on the exact requested_tier. This is a
    best-effort match against real audit history (not a hard DB link), so
    it can occasionally miscount an edge case (e.g. hospital changed tier
    again later for unrelated reasons) — good enough to act on, not
    perfectly authoritative."""
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    from app.utils.billing_cycle import TIER_MONTHLY_PRICE
    active_hospitals = db.query(Hospital).filter(Hospital.is_active == True).all()

    mrr_by_tier = {"foundation": 0, "growth": 0, "scale": 0, "enterprise": 0}
    for h in active_hospitals:
        if h.tier in mrr_by_tier:
            mrr_by_tier[h.tier] += TIER_MONTHLY_PRICE.get(h.tier, 0)
    mrr = sum(mrr_by_tier.values())
    arr = mrr * 12

    total_leads = db.query(func.count(HospitalLead.id)).scalar() or 0
    contacted_leads = db.query(func.count(HospitalLead.id)).filter(HospitalLead.status == "contacted").scalar() or 0

    upgrade_requests = db.query(UpgradeRequest).all()
    total_upgrade_requests = len(upgrade_requests)
    converted_upgrade_requests = 0
    for ur in upgrade_requests:
        later_changes = db.query(AuditLog).filter(
            AuditLog.hospital_id == ur.hospital_id,
            AuditLog.action == "hospital_tier_changed",
            AuditLog.created_at >= ur.created_at,
        ).all()
        for change in later_changes:
            m = re.match(r"Tier changed from (\w+) to (\w+)", change.details or "")
            if m and m.group(2) == ur.requested_tier:
                converted_upgrade_requests += 1
                break

    upgrade_conversion_rate = round((converted_upgrade_requests / total_upgrade_requests) * 100, 1) if total_upgrade_requests else 0

    return {
        "mrr": mrr,
        "arr": arr,
        "mrr_by_tier": mrr_by_tier,
        "total_hospital_leads": total_leads,
        "contacted_hospital_leads": contacted_leads,
        "lead_conversion_tracked": False,
        "total_upgrade_requests": total_upgrade_requests,
        "converted_upgrade_requests": converted_upgrade_requests,
        "upgrade_conversion_rate": upgrade_conversion_rate,
    }

@router.get("/analytics/platform/module-usage")
def platform_module_usage_analytics(
    trend_interval: str = "monthly",
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Phase 1 — Module usage, platform-wide (Radiology, cross-hospital
    Referrals, Suggestion box). CrossHospitalReferral has no single
    'accepted' status — pending/rejected/departed/admitted/expired — so
    'admitted' is used as the accepted-equivalent (referral resulted in a
    real admission at the receiving hospital)."""
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    if trend_interval not in ("monthly", "weekly"):
        raise HTTPException(status_code=400, detail="trend_interval must be 'monthly' or 'weekly'")

    from app.models.radiology_order import RadiologyOrder
    from app.models.cross_hospital_referral import CrossHospitalReferral

    now = now_ist_naive()
    bucket_count = 12
    trunc_unit = "month" if trend_interval == "monthly" else "week"

    if trend_interval == "monthly":
        period_start = (now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                         - relativedelta(months=bucket_count - 1))
        bucket_starts = [period_start + relativedelta(months=i) for i in range(bucket_count)]
        period_labels = [b.strftime("%Y-%m") for b in bucket_starts]
        fmt = "%Y-%m"
    else:
        this_monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        period_start = this_monday - timedelta(weeks=bucket_count - 1)
        bucket_starts = [period_start + timedelta(weeks=i) for i in range(bucket_count)]
        period_labels = [b.strftime("%Y-%m-%d") for b in bucket_starts]
        fmt = "%Y-%m-%d"

    def _trend_from(model, date_col):
        rows = (
            db.query(func.date_trunc(trunc_unit, date_col).label("bucket"), func.count(model.id))
            .filter(date_col >= period_start)
            .group_by("bucket")
            .all()
        )
        counted = {r[0].strftime(fmt): r[1] for r in rows if r[0] is not None}
        return [{"period": label, "count": counted.get(label, 0)} for label in period_labels]

    # ── Radiology ──
    total_radiology_orders = db.query(func.count(RadiologyOrder.id)).scalar() or 0
    radiology_by_type_rows = (
        db.query(RadiologyOrder.study_type, func.count(RadiologyOrder.id))
        .group_by(RadiologyOrder.study_type)
        .all()
    )
    radiology_by_type = {t: c for t, c in radiology_by_type_rows}
    radiology_trend = _trend_from(RadiologyOrder, RadiologyOrder.created_at)

    # ── Cross-hospital referrals ──
    total_referrals = db.query(func.count(CrossHospitalReferral.id)).scalar() or 0
    referral_status_rows = (
        db.query(CrossHospitalReferral.status, func.count(CrossHospitalReferral.id))
        .group_by(CrossHospitalReferral.status)
        .all()
    )
    referral_by_status = {s: c for s, c in referral_status_rows}
    referral_trend = _trend_from(CrossHospitalReferral, CrossHospitalReferral.created_at)

    # ── Suggestion box ──
    total_suggestions = db.query(func.count(Suggestion.id)).scalar() or 0
    resolved_suggestions = db.query(func.count(Suggestion.id)).filter(Suggestion.status == "completed").scalar() or 0
    suggestion_status_rows = (
        db.query(Suggestion.status, func.count(Suggestion.id))
        .group_by(Suggestion.status)
        .all()
    )
    suggestion_by_status = {s: c for s, c in suggestion_status_rows}
    suggestion_resolution_rate = round((resolved_suggestions / total_suggestions) * 100, 1) if total_suggestions else 0

    # Phase 3 addition — avg resolution time for completed suggestions
    completed_with_times = db.query(Suggestion.created_at, Suggestion.updated_at).filter(Suggestion.status == "completed").all()
    if completed_with_times:
        total_hours = sum((updated - created).total_seconds() / 3600 for created, updated in completed_with_times)
        avg_resolution_hours = round(total_hours / len(completed_with_times), 1)
    else:
        avg_resolution_hours = None

    return {
        "trend_interval": trend_interval,
        "radiology": {
            "total_orders": total_radiology_orders,
            "by_study_type": radiology_by_type,
            "trend": radiology_trend,
        },
        "referrals": {
            "total": total_referrals,
            "by_status": referral_by_status,
            "trend": referral_trend,
        },
        "suggestions": {
            "total": total_suggestions,
            "resolved": resolved_suggestions,
            "resolution_rate": suggestion_resolution_rate,
            "by_status": suggestion_by_status,
            "avg_resolution_hours": avg_resolution_hours,
        },
    }

@router.patch("/hospital/{hospital_id}/details")
def update_hospital(
    hospital_id: int,
    name: str,
    city: str,
    state: str,
    address: str = "",
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    hospital.name = name
    hospital.city = city
    hospital.state = state
    hospital.address = address
    db.commit()

    log_action(
        db, current_doctor,
        action="hospital_updated",
        target_type="hospital",
        target_id=hospital.id,
        target_label=hospital.name,
        hospital_id=hospital.id
    )
    return {"id": hospital.id, "name": hospital.name, "city": hospital.city, "state": hospital.state, "address": hospital.address}

@router.patch("/accounts/{doctor_id}")
def update_account(
    doctor_id: int,
    name: str,
    email: str,
    phone: str,
    title: str = None,
    specialization: str = "",
    room_number: str = "",
    consultation_fee: float = None,
    professional_fee_per_admission: float = None,
    role: str = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["super_admin", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    query = db.query(Doctor).filter(Doctor.id == doctor_id)
    if current_doctor.role.value == "admin":
        query = query.filter(Doctor.hospital_id == current_doctor.hospital_id)

    account = query.first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if role is not None:
        if account.role.value in ["admin", "super_admin"]:
            raise HTTPException(status_code=403, detail="Cannot change role of an admin account")
        if role not in ["doctor", "sub_admin", "receptionist", "nurse", "assistant", "lab", "pharmacy", "radiology"]:
            raise HTTPException(status_code=400, detail="Invalid role")
        account.role = UserRole(role)
        if role not in ["doctor", "sub_admin"]:
            account.consultation_fee = None
            account.professional_fee_per_admission = None

    email = email.lower().strip()
    existing = db.query(Doctor).filter(Doctor.email == email, Doctor.id != doctor_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    account.name = name
    account.email = email
    account.phone = phone
    if title:
        account.title = title
    if specialization:
        account.specialization = specialization
    if room_number is not None:
        account.room_number = room_number or None
    if consultation_fee is not None:
        account.consultation_fee = consultation_fee
    if professional_fee_per_admission is not None:
        account.professional_fee_per_admission = professional_fee_per_admission
    db.commit()

    log_action(
        db, current_doctor,
        action="account_updated",
        target_type="doctor",
        target_id=account.id,
        target_label=f"{account.title} {account.name}",
        hospital_id=account.hospital_id
    )
    return {"id": account.id, "name": account.name, "email": account.email, "phone": account.phone}

@router.patch("/accounts/{doctor_id}/toggle-active")
def toggle_account_active(
    doctor_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    account = db.query(Doctor).filter(
        Doctor.id == doctor_id,
        Doctor.role.in_([UserRole.admin, UserRole.sub_admin])
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    account.is_active = not account.is_active
    db.commit()

    log_action(
        db, current_doctor,
        action="account_activated" if account.is_active else "account_deactivated",
        target_type="doctor",
        target_id=account.id,
        target_label=f"{account.title} {account.name}",
        hospital_id=account.hospital_id
    )
    return {"id": account.id, "is_active": account.is_active}

@router.post("/accounts/{doctor_id}/reset-password")
def reset_account_password(
    doctor_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    account = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    import string
    alphabet = string.ascii_letters + string.digits
    new_password = "A1" + "".join(secrets.choice(alphabet) for _ in range(8))

    account.hashed_password = hash_password(new_password)
    account.must_change_password = True
    account.failed_login_attempts = 0
    account.locked_until = None
    db.commit()

    log_action(
        db, current_doctor,
        action="password_reset",
        target_type="doctor",
        target_id=account.id,
        target_label=f"{account.title} {account.name}",
        hospital_id=account.hospital_id
    )
    return {"id": account.id, "new_password": new_password}

@router.get("/test-catalog")
def list_test_catalog(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    from app.models.test_catalog import TestCatalogItem
    items = db.query(TestCatalogItem).filter(
        TestCatalogItem.hospital_id == current_doctor.hospital_id
    ).all()
    return [{"id": i.id, "name": i.name, "fee": i.fee, "is_active": i.is_active} for i in items]

@router.post("/test-catalog")
def create_test_catalog_item(
    name: str,
    fee: float,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    from app.models.test_catalog import TestCatalogItem
    item = TestCatalogItem(hospital_id=current_doctor.hospital_id, name=name, fee=fee, is_active=True)
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "name": item.name, "fee": item.fee, "is_active": item.is_active}

@router.patch("/test-catalog/{item_id}/toggle-active")
def toggle_test_catalog_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    from app.models.test_catalog import TestCatalogItem
    item = db.query(TestCatalogItem).filter(
        TestCatalogItem.id == item_id,
        TestCatalogItem.hospital_id == current_doctor.hospital_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Test not found")

    item.is_active = not item.is_active
    db.commit()
    return {"id": item.id, "is_active": item.is_active}

def _resolve_date_range(range_key: str, from_date: str, to_date: str, now):
    """Shared range resolver for hospital-wise drill-down analytics —
    today/7d/30d/custom rather than one hardcoded window per metric."""
    if range_key == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif range_key == "7d":
        end = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        start = end - timedelta(days=7)
    elif range_key == "30d":
        end = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        start = end - timedelta(days=30)
    elif range_key == "custom":
        if not from_date or not to_date:
            raise HTTPException(status_code=400, detail="from_date and to_date are required for range=custom")
        try:
            start = datetime.strptime(from_date, "%Y-%m-%d")
            end = datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1)
        except ValueError:
            raise HTTPException(status_code=400, detail="from_date/to_date must be YYYY-MM-DD")
    else:
        raise HTTPException(status_code=400, detail="range must be one of: today, 7d, 30d, custom")
    return start, end


@router.get("/analytics/hospital/{hospital_id}/staff-patients")
def hospital_staff_patients_analytics(
    hospital_id: int,
    range: str = "30d",
    from_date: str = None,
    to_date: str = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Phase 2 — Staff + Patients volume/patterns for one hospital's
    Analytics tab. Weekly pattern is all-time (not range-scoped) — a
    day-of-week pattern over just 7-30 days isn't a meaningful signal."""
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    now = now_ist_naive()
    start, end = _resolve_date_range(range, from_date, to_date, now)

    # ── Staff by role ──
    staff_rows = (
        db.query(Doctor.role, func.count(Doctor.id))
        .filter(Doctor.hospital_id == hospital_id, Doctor.is_active == True)
        .group_by(Doctor.role)
        .all()
    )
    staff_by_role = {}
    for role, count in staff_rows:
        key = "admin" if role.value in ("admin", "sub_admin") else role.value
        staff_by_role[key] = staff_by_role.get(key, 0) + count
    total_staff = sum(staff_by_role.values())

    # ── Patients — totals & portal adoption (all-time) ──
    total_patients = db.query(func.count(Patient.id)).filter(Patient.hospital_id == hospital_id).scalar() or 0
    portal_activated = (
        db.query(func.count(func.distinct(PatientProfileLink.patient_id)))
        .join(Patient, Patient.id == PatientProfileLink.patient_id)
        .filter(Patient.hospital_id == hospital_id)
        .scalar() or 0
    )

    # ── Patients per day trend (range-scoped, DB-grouped, zero-filled) ──
    day_rows = (
        db.query(func.date_trunc("day", Patient.created_at).label("day"), func.count(Patient.id))
        .filter(Patient.hospital_id == hospital_id, Patient.created_at >= start, Patient.created_at < end)
        .group_by("day")
        .all()
    )
    day_counts = {r[0].strftime("%Y-%m-%d"): r[1] for r in day_rows if r[0] is not None}
    patients_per_day = []
    cursor = start
    while cursor < end:
        label = cursor.strftime("%Y-%m-%d")
        patients_per_day.append({"date": label, "count": day_counts.get(label, 0)})
        cursor += timedelta(days=1)

    # ── Weekly pattern (all-time, day-of-week aggregate) ──
    dow_rows = (
        db.query(func.extract("dow", Patient.created_at).label("dow"), func.count(Patient.id))
        .filter(Patient.hospital_id == hospital_id)
        .group_by("dow")
        .all()
    )
    # Postgres dow: 0=Sunday..6=Saturday — remap to Mon..Sun for display
    dow_counts = {int(r[0]): r[1] for r in dow_rows if r[0] is not None}
    weekly_pattern = [
        {"day": label, "count": dow_counts.get(pg_dow, 0)}
        for label, pg_dow in [("Mon", 1), ("Tue", 2), ("Wed", 3), ("Thu", 4), ("Fri", 5), ("Sat", 6), ("Sun", 0)]
    ]

    return {
        "hospital_id": hospital_id,
        "hospital_name": hospital.name,
        "range": range,
        "range_start": start.strftime("%Y-%m-%d"),
        "range_end": (end - timedelta(days=1)).strftime("%Y-%m-%d"),
        "total_staff": total_staff,
        "staff_by_role": staff_by_role,
        "total_patients": total_patients,
        "portal_activated_patients": portal_activated,
        "portal_adoption_rate": round((portal_activated / total_patients) * 100, 1) if total_patients else 0,
        "patients_per_day": patients_per_day,
        "weekly_pattern": weekly_pattern,
    }


@router.get("/analytics/hospital/{hospital_id}/booking-behavior")
def hospital_booking_behavior_analytics(
    hospital_id: int,
    range: str = "30d",
    from_date: str = None,
    to_date: str = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Phase 2 — Booking behavior for one hospital: online vs walk-in
    ratio, and no-show rate on online bookings. No-show rate denominator is
    completed + no_show only — a cancelled booking is a different outcome,
    not a no-show, so it's excluded rather than silently counted either way."""
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    from app.models.checkin import Checkin
    from app.models.portal import Appointment, AppointmentStatus

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    now = now_ist_naive()
    start, end = _resolve_date_range(range, from_date, to_date, now)
    start_date, end_date = start.date(), end.date()

    # ── Online vs walk-in ratio ──
    source_rows = (
        db.query(Checkin.source, func.count(Checkin.id))
        .filter(Checkin.hospital_id == hospital_id, Checkin.visit_date >= start_date, Checkin.visit_date < end_date)
        .group_by(Checkin.source)
        .all()
    )
    source_counts = {s: c for s, c in source_rows}
    online_checkins = source_counts.get("online", 0)
    walkin_checkins = source_counts.get("walk_in", 0)
    total_checkins = online_checkins + walkin_checkins

    # ── Daily trend of online vs walk-in, zero-filled ──
    daily_rows = (
        db.query(Checkin.visit_date, Checkin.source, func.count(Checkin.id))
        .filter(Checkin.hospital_id == hospital_id, Checkin.visit_date >= start_date, Checkin.visit_date < end_date)
        .group_by(Checkin.visit_date, Checkin.source)
        .all()
    )
    daily_map = {}
    for d, src, cnt in daily_rows:
        label = d.strftime("%Y-%m-%d")
        daily_map.setdefault(label, {"online": 0, "walk_in": 0})[src] = cnt
    booking_trend = []
    cursor = start_date
    while cursor < end_date:
        label = cursor.strftime("%Y-%m-%d")
        vals = daily_map.get(label, {"online": 0, "walk_in": 0})
        booking_trend.append({"date": label, "online": vals.get("online", 0), "walk_in": vals.get("walk_in", 0)})
        cursor += timedelta(days=1)

    # ── No-show rate on online bookings ──
    resolved_appointments = (
        db.query(func.count(Appointment.id))
        .filter(
            Appointment.hospital_id == hospital_id,
            Appointment.requested_time >= start,
            Appointment.requested_time < end,
            Appointment.status.in_([AppointmentStatus.completed, AppointmentStatus.no_show]),
        )
        .scalar() or 0
    )
    no_show_count = (
        db.query(func.count(Appointment.id))
        .filter(
            Appointment.hospital_id == hospital_id,
            Appointment.requested_time >= start,
            Appointment.requested_time < end,
            Appointment.status == AppointmentStatus.no_show,
        )
        .scalar() or 0
    )
    no_show_rate = round((no_show_count / resolved_appointments) * 100, 1) if resolved_appointments else 0

    return {
        "hospital_id": hospital_id,
        "range": range,
        "range_start": start_date.strftime("%Y-%m-%d"),
        "range_end": (end_date - timedelta(days=1)).strftime("%Y-%m-%d"),
        "online_checkins": online_checkins,
        "walkin_checkins": walkin_checkins,
        "total_checkins": total_checkins,
        "online_ratio": round((online_checkins / total_checkins) * 100, 1) if total_checkins else 0,
        "booking_trend": booking_trend,
        "resolved_online_appointments": resolved_appointments,
        "no_show_count": no_show_count,
        "no_show_rate": no_show_rate,
    }


@router.get("/analytics/hospital/{hospital_id}/clinical-volume")
def hospital_clinical_volume_analytics(
    hospital_id: int,
    range: str = "30d",
    from_date: str = None,
    to_date: str = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Phase 2 — Clinical volume for one hospital: OPD trend, IPD trend,
    live bed occupancy. Average consultation duration is deliberately
    excluded — same reason as the platform-wide metric (no start/confirm
    timestamp pair on Consultation). Bed occupancy is a live snapshot, not
    range-scoped — 'currently admitted / total beds' doesn't have a
    meaningful range dimension."""
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    from app.models.admission import Admission
    from app.models.admission_ward_type import AdmissionWardType

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    now = now_ist_naive()
    start, end = _resolve_date_range(range, from_date, to_date, now)

    # ── OPD consultations trend (scoped via Patient join — Consultation has no hospital_id) ──
    opd_rows = (
        db.query(func.date_trunc("day", Consultation.created_at).label("day"), func.count(Consultation.id))
        .join(Patient, Patient.id == Consultation.patient_id)
        .filter(Patient.hospital_id == hospital_id, Consultation.created_at >= start, Consultation.created_at < end)
        .group_by("day")
        .all()
    )
    opd_counts = {r[0].strftime("%Y-%m-%d"): r[1] for r in opd_rows if r[0] is not None}

    # ── IPD admissions trend ──
    ipd_rows = (
        db.query(func.date_trunc("day", Admission.admission_date).label("day"), func.count(Admission.id))
        .filter(Admission.hospital_id == hospital_id, Admission.admission_date >= start, Admission.admission_date < end)
        .group_by("day")
        .all()
    )
    ipd_counts = {r[0].strftime("%Y-%m-%d"): r[1] for r in ipd_rows if r[0] is not None}

    opd_trend, ipd_trend = [], []
    cursor = start
    while cursor < end:
        label = cursor.strftime("%Y-%m-%d")
        opd_trend.append({"date": label, "count": opd_counts.get(label, 0)})
        ipd_trend.append({"date": label, "count": ipd_counts.get(label, 0)})
        cursor += timedelta(days=1)

    total_opd_in_range = sum(p["count"] for p in opd_trend)
    total_ipd_in_range = sum(p["count"] for p in ipd_trend)

    # ── Live bed occupancy ──
    total_beds = db.query(func.sum(AdmissionWardType.total_beds)).filter(
        AdmissionWardType.hospital_id == hospital_id
    ).scalar() or 0
    occupied_beds = db.query(func.count(Admission.id)).filter(
        Admission.hospital_id == hospital_id, Admission.status == "admitted"
    ).scalar() or 0
    occupancy_rate = round((occupied_beds / total_beds) * 100, 1) if total_beds else 0

    return {
        "hospital_id": hospital_id,
        "range": range,
        "range_start": start.strftime("%Y-%m-%d"),
        "range_end": (end - timedelta(days=1)).strftime("%Y-%m-%d"),
        "total_opd_in_range": total_opd_in_range,
        "opd_trend": opd_trend,
        "total_ipd_in_range": total_ipd_in_range,
        "ipd_trend": ipd_trend,
        "total_beds": total_beds,
        "occupied_beds": occupied_beds,
        "occupancy_rate": occupancy_rate,
        "average_consultation_duration": None,
    }


@router.get("/analytics/hospital/{hospital_id}/module-usage")
def hospital_module_usage_analytics(
    hospital_id: int,
    range: str = "30d",
    from_date: str = None,
    to_date: str = None,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Phase 2 — Module usage for one hospital: lab, pharmacy dispense,
    radiology, cross-hospital referrals sent/received. No tier gate is
    enforced here — showing real counts (0 if unused) rather than guessing
    at a gating rule that isn't actually in the backend."""
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    from app.models.test_order import TestOrder
    from app.models.medicine_order import MedicineOrder
    from app.models.radiology_order import RadiologyOrder
    from app.models.cross_hospital_referral import CrossHospitalReferral

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    now = now_ist_naive()
    start, end = _resolve_date_range(range, from_date, to_date, now)

    lab_orders = db.query(func.count(TestOrder.id)).filter(
        TestOrder.hospital_id == hospital_id, TestOrder.created_at >= start, TestOrder.created_at < end
    ).scalar() or 0

    pharmacy_dispensed = db.query(func.count(MedicineOrder.id)).filter(
        MedicineOrder.hospital_id == hospital_id,
        MedicineOrder.dispensed_at.isnot(None),
        MedicineOrder.dispensed_at >= start, MedicineOrder.dispensed_at < end
    ).scalar() or 0

    radiology_orders = db.query(func.count(RadiologyOrder.id)).filter(
        RadiologyOrder.hospital_id == hospital_id, RadiologyOrder.created_at >= start, RadiologyOrder.created_at < end
    ).scalar() or 0

    referrals_sent = db.query(func.count(CrossHospitalReferral.id)).filter(
        CrossHospitalReferral.from_hospital_id == hospital_id,
        CrossHospitalReferral.created_at >= start, CrossHospitalReferral.created_at < end
    ).scalar() or 0

    referrals_received = db.query(func.count(CrossHospitalReferral.id)).filter(
        CrossHospitalReferral.to_hospital_id == hospital_id,
        CrossHospitalReferral.created_at >= start, CrossHospitalReferral.created_at < end
    ).scalar() or 0

    return {
        "hospital_id": hospital_id,
        "range": range,
        "range_start": start.strftime("%Y-%m-%d"),
        "range_end": (end - timedelta(days=1)).strftime("%Y-%m-%d"),
        "lab_test_orders": lab_orders,
        "pharmacy_dispensed": pharmacy_dispensed,
        "radiology_orders": radiology_orders,
        "referrals_sent": referrals_sent,
        "referrals_received": referrals_received,
    }


@router.get("/analytics/platform/comparison")
def platform_month_over_month_comparison(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Phase 3 — This month vs last month, platform-wide. Uses equal-length
    windows (first N days of each month, where N = days elapsed in the
    current month) rather than month-to-date vs a full prior month, so the
    comparison stays fair on any day it's checked. MRR is reconstructed
    from tier-change audit history as of the equivalent point last month —
    see the note in the response."""
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    from app.models.admission import Admission
    from app.utils.billing_cycle import TIER_MONTHLY_PRICE

    now = now_ist_naive()
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elapsed = now - this_month_start
    last_month_start = this_month_start - relativedelta(months=1)
    last_month_asof = last_month_start + elapsed

    def pct_change(current, previous):
        if previous == 0:
            return None if current == 0 else 100.0
        return round(((current - previous) / previous) * 100, 1)

    def _window_count(model, date_col, w_start, w_end):
        return db.query(func.count(model.id)).filter(date_col >= w_start, date_col < w_end).scalar() or 0

    hosp_this = _window_count(Hospital, Hospital.created_at, this_month_start, now)
    hosp_last = _window_count(Hospital, Hospital.created_at, last_month_start, last_month_asof)

    patients_this = _window_count(Patient, Patient.created_at, this_month_start, now)
    patients_last = _window_count(Patient, Patient.created_at, last_month_start, last_month_asof)

    opd_this = _window_count(Consultation, Consultation.created_at, this_month_start, now)
    opd_last = _window_count(Consultation, Consultation.created_at, last_month_start, last_month_asof)

    ipd_this = _window_count(Admission, Admission.admission_date, this_month_start, now)
    ipd_last = _window_count(Admission, Admission.admission_date, last_month_start, last_month_asof)

    active_hospitals = db.query(Hospital).filter(Hospital.is_active == True).all()
    current_mrr = sum(TIER_MONTHLY_PRICE.get(h.tier, 0) for h in active_hospitals)

    last_month_mrr = 0
    for h in active_hospitals:
        if h.created_at >= last_month_asof:
            continue  # wasn't onboarded yet as of that point last month
        latest_change_before = (
            db.query(AuditLog)
            .filter(AuditLog.hospital_id == h.id, AuditLog.action == "hospital_tier_changed", AuditLog.created_at < last_month_asof)
            .order_by(AuditLog.created_at.desc())
            .first()
        )
        if latest_change_before:
            m = re.match(r"Tier changed from (\w+) to (\w+)", latest_change_before.details or "")
            tier_then = m.group(2) if m else h.tier
        else:
            tier_then = h.tier
        last_month_mrr += TIER_MONTHLY_PRICE.get(tier_then, 0)

    return {
        "as_of": now.strftime("%Y-%m-%d"),
        "window_days": elapsed.days,
        "hospitals_onboarded": {"this_period": hosp_this, "same_period_last_month": hosp_last, "change_pct": pct_change(hosp_this, hosp_last)},
        "new_patients": {"this_period": patients_this, "same_period_last_month": patients_last, "change_pct": pct_change(patients_this, patients_last)},
        "opd_consultations": {"this_period": opd_this, "same_period_last_month": opd_last, "change_pct": pct_change(opd_this, opd_last)},
        "ipd_admissions": {"this_period": ipd_this, "same_period_last_month": ipd_last, "change_pct": pct_change(ipd_this, ipd_last)},
        "mrr": {
            "this_period": current_mrr, "same_period_last_month": last_month_mrr, "change_pct": pct_change(current_mrr, last_month_mrr),
            "note": "same_period_last_month is reconstructed from tier-change audit history, not a stored snapshot",
        },
    }


@router.get("/analytics/platform/alerts")
def platform_alerts(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Phase 3 — Actionable alerts, platform-wide. Same underlying
    conditions as /admin/notifications-feed's billing/cap checks — this is
    a persistent list view of them for the Analytics tab, not a second
    data source."""
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    now = now_ist_naive()
    stale_cutoff = now - timedelta(days=3)

    ai_scribe_no_topup = []
    billing_ending_soon = []
    billing_grace_period = []

    for h in db.query(Hospital).filter(Hospital.is_active == True).all():
        if has_ai_scribe_at_all(h.tier):
            cap = AI_SCRIBE_TIER_CAPS.get(h.tier)
            if cap:
                pct = (h.ai_scribe_consultations_used / cap) * 100
                if pct >= 80:
                    status_info = get_ai_scribe_status(db, h)
                    if status_info["topup_remaining"] == 0:
                        ai_scribe_no_topup.append({
                            "hospital_id": h.id, "hospital_name": h.name,
                            "used": h.ai_scribe_consultations_used, "cap": cap, "percent_used": round(pct, 1),
                        })

        info = get_billing_cycle_info(h)
        if info:
            if now < info["cycle_end"] and (info["cycle_end"] - now) <= timedelta(days=2):
                billing_ending_soon.append({
                    "hospital_id": h.id, "hospital_name": h.name,
                    "cycle_end": info["cycle_end"].strftime("%Y-%m-%d"),
                })
            elif info["cycle_end"] <= now < info["deactivation_at"]:
                billing_grace_period.append({
                    "hospital_id": h.id, "hospital_name": h.name,
                    "deactivation_at": info["deactivation_at"].strftime("%Y-%m-%d"),
                })

    stale_leads = [
        {"lead_id": l.id, "hospital_name": l.hospital_name, "created_at": l.created_at.strftime("%Y-%m-%d")}
        for l in db.query(HospitalLead).filter(HospitalLead.status == "new", HospitalLead.created_at < stale_cutoff).all()
    ]
    stale_upgrade_requests = [
        {"request_id": u.id, "hospital_id": u.hospital_id, "requested_tier": u.requested_tier, "created_at": u.created_at.strftime("%Y-%m-%d")}
        for u in db.query(UpgradeRequest).filter(UpgradeRequest.status == "new", UpgradeRequest.created_at < stale_cutoff).all()
    ]

    total_alerts = len(ai_scribe_no_topup) + len(billing_ending_soon) + len(billing_grace_period) + len(stale_leads) + len(stale_upgrade_requests)

    return {
        "total_alerts": total_alerts,
        "ai_scribe_no_topup": ai_scribe_no_topup,
        "billing_ending_soon": billing_ending_soon,
        "billing_grace_period": billing_grace_period,
        "stale_leads": stale_leads,
        "stale_upgrade_requests": stale_upgrade_requests,
    }


@router.get("/hospital/{hospital_id}")
def hospital_detail(
    hospital_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    if current_doctor.role.value != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    admins = db.query(Doctor).filter(
        Doctor.hospital_id == hospital_id,
        Doctor.role.in_([UserRole.admin, UserRole.sub_admin])
    ).all()

    doctors = db.query(Doctor).filter(
        Doctor.hospital_id == hospital_id,
        Doctor.role.in_([UserRole.doctor, UserRole.sub_admin])
    ).all()

    return {
        "id": hospital.id,
        "name": hospital.name,
        "city": hospital.city,
        "state": hospital.state,
        "address": hospital.address,
        "hospital_code": hospital.hospital_code,
        "hospital_type": hospital.hospital_type,
        "billing_enabled": hospital.billing_enabled,
        "tier": hospital.tier,
        "is_active": hospital.is_active,
        "created_at": hospital.created_at.isoformat(),
        **serialize_billing_block(db, hospital),
        "admins": [
            {
                "id": a.id,
                "name": f"{a.title} {a.name}",
                "email": a.email,
                "phone": a.phone,
                "role": a.role.value,
                "is_active": a.is_active
            }
            for a in admins
        ],
        "doctors": [
            {
                "id": d.id,
                "name": f"{d.title} {d.name}",
                "specialization": d.specialization,
                "is_active": d.is_active
            }
            for d in doctors
        ],
        "doctor_count": len(doctors),
        "monthly_revenue": len(doctors) * 499
    }