import json
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.admission import Admission, AdmissionMedicationOrder
from app.models.admission_vitals import AdmissionVitals
from app.models.admission_progress_note import AdmissionProgressNote
from app.models.admission_ward_type import AdmissionWardType
from app.models.cross_hospital_referral import CrossHospitalReferral
from app.models.doctor import Doctor
from app.models.hospital import Hospital
from app.models.patient import Patient
from app.models.test_order import TestOrder
from app.schemas.cross_hospital_referral import RejectReferralIn, RejectAndForwardIn
from app.utils.auth import get_current_doctor
from app.utils.audit import log_action
from app.utils.timezone import now_ist_naive
from app.utils.notify import (
    notify_referral_incoming, notify_referral_departed, notify_referral_rejected, notify_referral_admin,
)

router = APIRouter(prefix="/referrals", tags=["referrals"])

TIER_ORDER = {"foundation": 0, "growth": 1, "scale": 2, "enterprise": 3}


def _require_scale_or_above(hospital: Hospital):
    """Server-side enforcement of the Scale/Enterprise-only outbound gate —
    the frontend upgrade-gate check is UX only, this is the real gate."""
    if TIER_ORDER.get(hospital.tier, 1) < TIER_ORDER["scale"]:
        raise HTTPException(status_code=403, detail="Outbound referral requires the Scale or Enterprise plan")


def _hospital_or_404(db: Session, hospital_id: int) -> Hospital:
    h = db.query(Hospital).filter(Hospital.id == hospital_id, Hospital.is_active == True).first()  # noqa: E712
    if not h:
        raise HTTPException(status_code=404, detail="Hospital not found")
    return h


def _expire_stale_cross_hospital_referrals(db: Session, hospital_id: int) -> None:
    """Same lazy-sweep-on-read pattern as _expire_stale_admission_referrals —
    no background scheduler in this codebase. Applies uniformly to every
    unactioned state at either side of the referral, per the 24h rule."""
    cutoff = now_ist_naive() - timedelta(hours=24)
    stale = db.query(CrossHospitalReferral).filter(
        (CrossHospitalReferral.from_hospital_id == hospital_id) | (CrossHospitalReferral.to_hospital_id == hospital_id),
        CrossHospitalReferral.status.in_(["pending", "departed"]),
        CrossHospitalReferral.created_at < cutoff,
    ).all()
    for r in stale:
        r.status = "expired"


def _snapshot_admission_clinical_data(db: Session, admission: Admission) -> dict:
    """Builds the clinical-record snapshot that travels with a referral.
    Deliberately never touches AdmissionCharge/Invoice/deposit data — no
    financial figure of any kind goes into this dict. Tests are shaped
    exactly like GET /lab/patient-reports/{id}'s response so the Reports
    modal's existing render logic can consume it unmodified."""
    vitals = db.query(AdmissionVitals).filter(AdmissionVitals.admission_id == admission.id).order_by(AdmissionVitals.recorded_at.asc()).all()
    vitals_out = [{"data": json.loads(v.data) if v.data else {}, "recorded_at": v.recorded_at.isoformat()} for v in vitals]

    meds = db.query(AdmissionMedicationOrder).filter(AdmissionMedicationOrder.admission_id == admission.id).all()
    meds_out = [{
        "medicine_name": m.medicine_name, "dosage": m.dosage, "route": m.route,
        "quantity": m.quantity, "is_active": m.is_active, "created_at": m.created_at.isoformat() if m.created_at else None,
    } for m in meds]

    orders = db.query(TestOrder).filter(TestOrder.admission_id == admission.id, TestOrder.status == "verified_released").all()
    tests_out = []
    for o in orders:
        try:
            raw_results = json.loads(o.result_data) if o.result_data else {}
        except Exception:
            raw_results = {}
        rows = [{"name": k, "value": v, "unit": "", "range": ""} for k, v in raw_results.items()]
        tests_out.append({
            "order_id": o.id, "test_name": o.test_name, "results": rows,
            "is_critical": o.is_critical, "verified_at": o.verified_at.isoformat() if o.verified_at else None,
        })
    visits_out = [{"date": now_ist_naive().isoformat(), "token_number": "", "tests": tests_out}] if tests_out else []

    notes = db.query(AdmissionProgressNote).filter(AdmissionProgressNote.admission_id == admission.id).order_by(AdmissionProgressNote.created_at.asc()).all()
    notes_out = [{"note": n.note, "created_at": n.created_at.isoformat()} for n in notes]

    return {
        "vitals": vitals_out,
        "medicines": meds_out,
        "visits": visits_out,
        "progress_notes": notes_out,
    }


def _serialize_referral(db: Session, r: CrossHospitalReferral) -> dict:
    from_h = db.query(Hospital).filter(Hospital.id == r.from_hospital_id).first()
    to_h = db.query(Hospital).filter(Hospital.id == r.to_hospital_id).first()
    return {
        "id": r.id, "chain_id": r.chain_id,
        "from_hospital_id": r.from_hospital_id, "from_hospital_name": from_h.name if from_h else "Unknown",
        "to_hospital_id": r.to_hospital_id, "to_hospital_name": to_h.name if to_h else "Unknown",
        "initiation_type": r.initiation_type,
        "patient_name": r.patient_name, "patient_age": r.patient_age, "patient_gender": r.patient_gender,
        "clinical_note": r.clinical_note, "diagnosis_snapshot": r.diagnosis_snapshot,
        "vitals": json.loads(r.vitals_snapshot_json) if r.vitals_snapshot_json else [],
        "medicines": json.loads(r.medicines_snapshot_json) if r.medicines_snapshot_json else [],
        "visits": json.loads(r.tests_snapshot_json) if r.tests_snapshot_json else [],
        "progress_notes": json.loads(r.progress_notes_snapshot_json) if r.progress_notes_snapshot_json else [],
        "status": r.status,
        "acknowledged_at": r.acknowledged_at.isoformat() if r.acknowledged_at else None,
        "rejected_at": r.rejected_at.isoformat() if r.rejected_at else None,
        "rejection_note": r.rejection_note,
        "departed_at": r.departed_at.isoformat() if r.departed_at else None,
        "admitted_at": r.admitted_at.isoformat() if r.admitted_at else None,
        "admitted_admission_id": r.admitted_admission_id,
        "expires_at": r.expires_at.isoformat(),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


# --- Target hospital directory (mirrors portal_hospitals.py's state/city/hospital pattern, staff-authed) ---

@router.get("/target-states")
def list_target_states(current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    rows = db.query(Hospital.state).filter(Hospital.is_active == True, Hospital.state.isnot(None)).distinct().all()  # noqa: E712
    return sorted({r[0] for r in rows if r[0]})


@router.get("/target-cities")
def list_target_cities(state: Optional[str] = Query(None), current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    q = db.query(Hospital.city).filter(Hospital.is_active == True, Hospital.city.isnot(None))  # noqa: E712
    if state:
        q = q.filter(Hospital.state == state)
    rows = q.distinct().all()
    return sorted({r[0] for r in rows if r[0]})


@router.get("/target-hospitals")
def list_target_hospitals(state: Optional[str] = Query(None), city: Optional[str] = Query(None), current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    """Excludes the referring hospital itself — inbound is unconditional for
    every tier, so no tier filter here at all."""
    q = db.query(Hospital).filter(Hospital.is_active == True, Hospital.id != current_doctor.hospital_id)  # noqa: E712
    if state:
        q = q.filter(Hospital.state == state)
    if city:
        q = q.filter(Hospital.city.ilike(f"%{city}%"))
    return [{"id": h.id, "name": h.name, "city": h.city, "state": h.state} for h in q.order_by(Hospital.name).all()]


@router.get("/target-hospitals/{hospital_id}/bed-summary")
def target_hospital_bed_summary(hospital_id: int, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    """Aggregate bed counts only, grouped by ward-type category — never
    room/bed-level detail, never a live hold on any bed."""
    _hospital_or_404(db, hospital_id)
    ward_types = db.query(AdmissionWardType).filter(AdmissionWardType.hospital_id == hospital_id).all()
    summary = {}
    for wt in ward_types:
        occupied = db.query(Admission).filter(Admission.ward_type_id == wt.id, Admission.status == "admitted").count()
        available = max(wt.total_beds - occupied, 0)
        label = wt.category.replace("_", " ").title() if wt.category else "General"
        summary[label] = summary.get(label, 0) + available
    return [{"category": k, "available": v} for k, v in summary.items()]


# --- Own default state/city, for pre-selecting the Refer modal's dropdowns ---

@router.get("/my-hospital-location")
def my_hospital_location(current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    h = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()
    return {"state": h.state if h else None, "city": h.city if h else None}


# --- Initiation lives on the admissions router: POST /admissions/{admission_id}/refer ---
# (kept there for URL consistency with the rest of the admission actions;
# it imports _snapshot_admission_clinical_data from this module.)


@router.get("/{referral_id}")
def get_referral(referral_id: int, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    r = db.query(CrossHospitalReferral).filter(CrossHospitalReferral.id == referral_id).first()
    if not r or current_doctor.hospital_id not in (r.from_hospital_id, r.to_hospital_id):
        raise HTTPException(status_code=404, detail="Referral not found")
    return _serialize_referral(db, r)


@router.post("/{referral_id}/acknowledge")
def acknowledge_referral(referral_id: int, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["receptionist", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    r = db.query(CrossHospitalReferral).filter(CrossHospitalReferral.id == referral_id, CrossHospitalReferral.to_hospital_id == current_doctor.hospital_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Referral not found")
    r.acknowledged_at = now_ist_naive()
    db.commit()
    return {"acknowledged": True}


@router.post("/{referral_id}/reject")
def reject_referral(referral_id: int, body: RejectReferralIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["receptionist", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    if not (body.rejection_note or "").strip():
        raise HTTPException(status_code=400, detail="A note explaining the rejection is required")

    r = db.query(CrossHospitalReferral).filter(CrossHospitalReferral.id == referral_id, CrossHospitalReferral.to_hospital_id == current_doctor.hospital_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Referral not found")
    if r.status != "pending":
        raise HTTPException(status_code=400, detail="This referral can no longer be rejected — the patient has already departed")

    r.status = "rejected"
    r.rejected_at = now_ist_naive()
    r.rejected_by = current_doctor.id
    r.rejection_note = body.rejection_note.strip()

    if r.source_admission_id:
        source_admission = db.query(Admission).filter(Admission.id == r.source_admission_id).first()
        if source_admission and source_admission.pending_outbound_referral_id == r.id:
            source_admission.pending_outbound_referral_id = None

    from_hospital = db.query(Hospital).filter(Hospital.id == r.from_hospital_id).first()
    to_hospital = db.query(Hospital).filter(Hospital.id == r.to_hospital_id).first()
    notify_referral_rejected(db, r.from_hospital_id, r.id, r.patient_name, to_hospital.name if to_hospital else "the hospital")

    # Symmetric rule: ANY pre-departure reject, regardless of B's tier, notifies
    # Hospital A's admin specifically (not just the hospital-wide nurse/doctor
    # ping above) and logs on Hospital A's side only.
    notify_referral_admin(db, r.from_hospital_id, r.id, f"Referral declined — {r.patient_name}",
                           f"{to_hospital.name if to_hospital else 'The receiving hospital'} declined the referral for {r.patient_name}. Reason: {body.rejection_note.strip()}")
    log_action(
        db, None, action="referral_rejected", target_type="cross_hospital_referral", target_id=r.id,
        target_label=f"{r.patient_name} referral from {to_hospital.name if to_hospital else '?'}",
        details=body.rejection_note.strip(), hospital_id=r.from_hospital_id,
    )

    db.commit()
    return {"message": f"Referral for {r.patient_name} rejected — {from_hospital.name if from_hospital else 'the referring hospital'} has been notified"}


@router.post("/{referral_id}/reject-and-forward")
def reject_and_forward_referral(referral_id: int, body: RejectAndForwardIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["receptionist", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    hospital = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()
    _require_scale_or_above(hospital)  # only Scale/Enterprise can forward to a third hospital

    if not (body.rejection_note or "").strip():
        raise HTTPException(status_code=400, detail="A note explaining the rejection is required")
    if not (body.clinical_note or "").strip():
        raise HTTPException(status_code=400, detail="A clinical note is required for the forwarded referral")

    r = db.query(CrossHospitalReferral).filter(CrossHospitalReferral.id == referral_id, CrossHospitalReferral.to_hospital_id == current_doctor.hospital_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Referral not found")
    if r.status != "departed":
        raise HTTPException(status_code=400, detail="Reject-and-forward is only available after the patient has departed the referring hospital")

    _hospital_or_404(db, body.to_hospital_id)
    if body.to_hospital_id == current_doctor.hospital_id:
        raise HTTPException(status_code=400, detail="Cannot forward to your own hospital")

    r.status = "rejected"
    r.rejected_at = now_ist_naive()
    r.rejected_by = current_doctor.id
    r.rejection_note = body.rejection_note.strip()

    forward = CrossHospitalReferral(
        chain_id=r.chain_id, from_hospital_id=current_doctor.hospital_id, to_hospital_id=body.to_hospital_id,
        source_admission_id=None, origin_patient_id=None,  # B never admitted this patient — no local patient/admission to link
        initiation_type="reject_forward", initiated_by=current_doctor.id, superseded_referral_id=r.id,
        patient_name=r.patient_name, patient_age=r.patient_age, patient_gender=r.patient_gender,
        clinical_note=body.clinical_note.strip(), diagnosis_snapshot=r.diagnosis_snapshot,
        vitals_snapshot_json=r.vitals_snapshot_json, medicines_snapshot_json=r.medicines_snapshot_json,
        tests_snapshot_json=r.tests_snapshot_json, progress_notes_snapshot_json=r.progress_notes_snapshot_json,
        status="pending", expires_at=now_ist_naive() + timedelta(hours=24),
    )
    db.add(forward)

    to_hospital_c = db.query(Hospital).filter(Hospital.id == body.to_hospital_id).first()
    notify_referral_incoming(db, body.to_hospital_id, forward.id, forward.patient_name, hospital.name)

    # B's admin sees both: (a) the original incoming referral that arrived
    # earlier, and (b) B's own reject-and-forward action — both notified
    # here and both logged in B's own audit log only.
    from_hospital_a = db.query(Hospital).filter(Hospital.id == r.from_hospital_id).first()
    notify_referral_admin(db, current_doctor.hospital_id, r.id, f"Incoming referral — {r.patient_name}",
                           f"{from_hospital_a.name if from_hospital_a else 'A hospital'} referred {r.patient_name} to you.")
    notify_referral_admin(db, current_doctor.hospital_id, r.id, f"Referral rejected & forwarded — {r.patient_name}",
                           f"{r.patient_name}'s referral was rejected and forwarded to {to_hospital_c.name if to_hospital_c else 'another hospital'}.")
    log_action(
        db, current_doctor, action="referral_rejected_and_forwarded", target_type="cross_hospital_referral",
        target_id=r.id, target_label=r.patient_name,
        details=f"Rejected: {body.rejection_note.strip()} | Forwarded to {to_hospital_c.name if to_hospital_c else body.to_hospital_id}: {body.clinical_note.strip()}",
    )

    db.commit()
    return {"message": f"Rejected and forwarded to {to_hospital_c.name if to_hospital_c else 'the next hospital'}", "new_referral_id": forward.id}


@router.get("/records/for-admission/{admission_id}")
def get_referral_chain_for_admission(admission_id: str, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    admission = db.query(Admission).filter(Admission.public_token == admission_id, Admission.hospital_id == current_doctor.hospital_id).first()
    if not admission or not admission.received_via_referral_id:
        raise HTTPException(status_code=404, detail="This admission did not arrive via referral")

    entry_referral = db.query(CrossHospitalReferral).filter(CrossHospitalReferral.id == admission.received_via_referral_id).first()
    if not entry_referral:
        raise HTTPException(status_code=404, detail="Referral record not found")

    hops = db.query(CrossHospitalReferral).filter(
        CrossHospitalReferral.chain_id == entry_referral.chain_id
    ).order_by(CrossHospitalReferral.created_at.asc()).all()

    out = []
    for hop in hops:
        from_h = db.query(Hospital).filter(Hospital.id == hop.from_hospital_id).first()
        out.append({
            "hospital_name": from_h.name if from_h else "Unknown",
            "diagnosis": hop.diagnosis_snapshot,
            "clinical_note": hop.clinical_note,
            "vitals": json.loads(hop.vitals_snapshot_json) if hop.vitals_snapshot_json else [],
            "medicines": json.loads(hop.medicines_snapshot_json) if hop.medicines_snapshot_json else [],
            "visits": json.loads(hop.tests_snapshot_json) if hop.tests_snapshot_json else [],
            "progress_notes": json.loads(hop.progress_notes_snapshot_json) if hop.progress_notes_snapshot_json else [],
        })
    return out