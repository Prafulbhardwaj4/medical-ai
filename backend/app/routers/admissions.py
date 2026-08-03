import secrets
from datetime import datetime, date as date_cls

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.admission import Admission, AdmissionMedicationOrder, AdmissionMedicationAdministration, AdmissionCharge, AdmissionMedicationReturn
from app.models.admission_ward_type import AdmissionWardType
from app.models.admission_ward_stay import AdmissionWardStay
from app.models.admission_referral import AdmissionReferral
from app.models.patient import Patient
from app.models.doctor import Doctor
from app.models.hospital import Hospital
from app.models.hospital_medicine import HospitalMedicine
from app.models.test_order import TestOrder
from app.models.invoice import Invoice
from app.models.notification import Notification
from app.models.admission_deposit import AdmissionDeposit, AdmissionDepositTopupRequest
from app.models.admission_tpa_case import AdmissionTpaCase
from app.models.admission_consent import AdmissionConsent
from app.models.credit_debit_note import CreditDebitNote
from app.models.refund import Refund
from app.schemas.admission import (
    AdmitPatientIn, AddMedicationOrderIn, AdministerDoseIn, AddChargeIn, AddAdmissionTestIn, DischargeIn,
    WardTypeCreateIn, WardTypeOut, UpdateDiagnosisIn, RequestWardChangeIn, ChangeWardIn, SendToAdmissionIn,
    TopupRequestIn, CollectTopupIn, TpaCaseIn, TpaCaseUpdateIn, ReturnMedicationIn, EmergencyAlertIn,
    ProfessionalFeeIn, VALID_ADMISSION_TYPES, AdmissionConsentIn, VALID_CONSENT_TYPES, VALID_DISCHARGE_TYPES,
    VALID_WARD_CATEGORIES, TpaSettleIn,
)
from app.models.consultation import Consultation
from app.utils.auth import get_current_doctor, ist_today
from app.utils.timezone import now_ist_naive
from app.utils.inventory import deduct_stock_fefo
from app.utils.notify import notify_ward_change_request, notify_emergency_alert
from app.utils.receipts import next_receipt_number, next_note_number
from app.utils.gst import apply_gst
from app.services.pdf_service import generate_invoice_pdf
import json

router = APIRouter(prefix="/admissions", tags=["admissions"])


def _days_admitted(admission: Admission) -> int:
    end = admission.discharge_date or now_ist_naive()
    days = (end.date() - admission.admission_date.date()).days + 1
    return max(days, 1)


def _current_daily_rate(db: Session, admission: Admission) -> float:
    """The rate to actually bill at — uses the ward type's CURRENT daily_charge if it
    still exists (so an admin's mid-stay rate change is honored at billing time),
    falling back to the snapshot taken at admit time otherwise."""
    if admission.ward_type_id:
        wt = db.query(AdmissionWardType).filter(AdmissionWardType.id == admission.ward_type_id).first()
        if wt:
            return wt.daily_charge
    return admission.daily_room_charge


def _room_charge_breakdown(db: Session, admission: Admission):
    """Returns (breakdown_list, total). Sums each ward-stay segment's own
    (days * daily_charge) rather than applying the current ward's rate to the
    whole admission — so a mid-stay move to/from ICU only re-rates the days
    actually spent there."""
    if admission.admission_type == "day_care":
        # Day-care/short-stay never accrues overnight bed-night charges —
        # everything else (medicine, tests, procedures, professional fee)
        # still bills normally.
        return [], 0.0

    stays = db.query(AdmissionWardStay).filter(
        AdmissionWardStay.admission_id == admission.id
    ).order_by(AdmissionWardStay.start_date.asc()).all()

    if not stays:
        # Admissions created before this feature existed have no segments — fall back
        # to the old single-rate calculation so their bills don't break.
        days = _days_admitted(admission)
        rate = _current_daily_rate(db, admission)
        return [{"ward": admission.ward, "bed_number": admission.bed_number, "days": days,
                 "daily_charge": rate, "amount": days * rate, "start_date": admission.admission_date.isoformat(),
                 "end_date": admission.discharge_date.isoformat() if admission.discharge_date else None}], days * rate

    breakdown = []
    total = 0.0
    last_index = len(stays) - 1
    for i, s in enumerate(stays):
        seg_end = s.end_date or admission.discharge_date or now_ist_naive()
        days = (seg_end.date() - s.start_date.date()).days
        if i == last_index:
            days += 1  # the current/last segment's start day counts as a full day, same convention as before
        days = max(days, 0)
        amount = days * s.daily_charge
        breakdown.append({
            "ward": s.ward_name, "bed_number": s.bed_number, "days": days, "daily_charge": s.daily_charge,
            "amount": amount, "start_date": s.start_date.isoformat(), "end_date": s.end_date.isoformat() if s.end_date else None,
        })
        total += amount
    return breakdown, total


def _room_total(db: Session, admission: Admission) -> float:
    _, total = _room_charge_breakdown(db, admission)
    return total


def _ward_type_initials(name: str) -> str:
    import re
    words = [w for w in re.split(r"\s+", name.strip()) if w]
    if len(words) > 1:
        return "".join(w[0] for w in words).upper()[:4]
    return re.sub(r"[^A-Za-z]", "", name)[:3].upper() or "WD"


def _bed_labels_for_ward_type(wt: AdmissionWardType) -> list[str]:
    initials = _ward_type_initials(wt.name)
    return [f"{initials}-{i}" for i in range(1, wt.total_beds + 1)]


def _get_admission_or_404(db: Session, admission_token: str, hospital_id: int) -> Admission:
    a = db.query(Admission).filter(Admission.public_token == admission_token, Admission.hospital_id == hospital_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Admission not found")
    return a


@router.get("/last-diagnosis/{patient_id}")
def last_diagnosis(patient_id: int, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    """Suggests a starting diagnosis from the patient's most recent consultation.
    Purely a convenience prefill — diagnosis is still required and freely editable on admit."""
    last = db.query(Consultation).filter(
        Consultation.patient_id == patient_id
    ).order_by(Consultation.created_at.desc()).first()
    return {"diagnosis": last.diagnosis if last and last.diagnosis else None}


@router.get("/last-doctor/{patient_id}")
def last_doctor(patient_id: int, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    """Suggests the patient's actual last consulting doctor as the admitting doctor —
    NOT whoever is performing the admission (reception), which was the previous bug."""
    last = db.query(Consultation).filter(
        Consultation.patient_id == patient_id
    ).order_by(Consultation.created_at.desc()).first()
    if not last:
        return {"doctor_id": None, "doctor_name": None}
    doc = db.query(Doctor).filter(Doctor.id == last.doctor_id).first()
    return {"doctor_id": last.doctor_id, "doctor_name": f"{doc.title} {doc.name}" if doc else None}


@router.patch("/{admission_id}/diagnosis")
def update_diagnosis(admission_id: str, body: UpdateDiagnosisIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if not body.diagnosis.strip():
        raise HTTPException(status_code=400, detail="Diagnosis cannot be empty")
    admission = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    admission.diagnosis = body.diagnosis.strip()
    db.commit()
    return {"message": "Diagnosis updated", "diagnosis": admission.diagnosis}


@router.post("")
def admit_patient(body: AdmitPatientIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.id == body.patient_id, Patient.hospital_id == current_doctor.hospital_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    already_admitted = db.query(Admission).filter(Admission.patient_id == patient.id, Admission.status == "admitted").first()
    if already_admitted:
        raise HTTPException(status_code=400, detail="This patient is already admitted")

    from app.models.checkin import Checkin
    checked_in_today = db.query(Checkin).filter(
        Checkin.patient_id == patient.id, Checkin.visit_date == ist_today()
    ).first()
    if not checked_in_today:
        raise HTTPException(status_code=400, detail="This patient must be physically checked in today (an active token) before they can be admitted")

    referral = db.query(AdmissionReferral).filter(
        AdmissionReferral.patient_id == patient.id, AdmissionReferral.status == "pending"
    ).first()
    if not referral:
        raise HTTPException(status_code=400, detail="A doctor must send this patient for admission before reception can process it")

    ward_name = body.ward
    daily_charge = body.daily_room_charge
    ward_type_id = None

    if not (body.diagnosis or "").strip():
        raise HTTPException(status_code=400, detail="Diagnosis is required")

    admission_type = (body.admission_type or "planned").strip().lower()
    if admission_type not in VALID_ADMISSION_TYPES:
        raise HTTPException(status_code=400, detail="Invalid admission type")

    if body.admitting_doctor_id:
        admitting_doctor = db.query(Doctor).filter(
            Doctor.id == body.admitting_doctor_id, Doctor.hospital_id == current_doctor.hospital_id
        ).first()
        if not admitting_doctor:
            raise HTTPException(status_code=404, detail="Admitting doctor not found")
        admitting_doctor_id = admitting_doctor.id
    else:
        last_consultation = db.query(Consultation).filter(
            Consultation.patient_id == patient.id
        ).order_by(Consultation.created_at.desc()).first()
        if not last_consultation:
            raise HTTPException(status_code=400, detail="No consultation history found for this patient — please select the admitting doctor manually")
        admitting_doctor_id = last_consultation.doctor_id

    if body.ward_type_id:
        ward_type = db.query(AdmissionWardType).filter(
            AdmissionWardType.id == body.ward_type_id, AdmissionWardType.hospital_id == current_doctor.hospital_id
        ).first()
        if not ward_type:
            raise HTTPException(status_code=404, detail="Ward type not found")
        occupied_labels = {
            a.bed_number for a in db.query(Admission).filter(
                Admission.ward_type_id == ward_type.id, Admission.status == "admitted"
            ).all()
        }
        if len(occupied_labels) >= ward_type.total_beds:
            raise HTTPException(status_code=400, detail=f"No beds available in {ward_type.name}")
        valid_labels = set(_bed_labels_for_ward_type(ward_type))
        if not body.bed_number or body.bed_number not in valid_labels:
            raise HTTPException(status_code=400, detail="Please select a valid bed")
        if body.bed_number in occupied_labels:
            raise HTTPException(status_code=400, detail=f"Bed {body.bed_number} is already occupied — pick another")
        ward_name = ward_type.name
        daily_charge = ward_type.daily_charge
        ward_type_id = ward_type.id
    elif not ward_name:
        raise HTTPException(status_code=400, detail="Ward is required")

    if body.deposit_amount < 0:
        raise HTTPException(status_code=400, detail="Deposit cannot be negative")
    if body.deposit_amount > 0 and not body.deposit_payment_method:
        raise HTTPException(status_code=400, detail="Please select how the deposit was collected")

    admission = Admission(
        patient_id=patient.id, hospital_id=current_doctor.hospital_id,
        admitting_doctor_id=admitting_doctor_id, ward=ward_name, ward_type_id=ward_type_id, bed_number=body.bed_number,
        diagnosis=body.diagnosis, daily_room_charge=daily_charge,
        status="admitted", admission_date=now_ist_naive(),
        public_token=secrets.token_urlsafe(16),
        admission_type=admission_type,
    )
    db.add(admission)
    referral.status = "admitted"
    db.commit()
    db.refresh(admission)

    db.add(AdmissionWardStay(
        admission_id=admission.id, ward_type_id=ward_type_id, ward_name=ward_name,
        bed_number=body.bed_number, daily_charge=daily_charge, start_date=admission.admission_date,
    ))

    if body.deposit_amount > 0:
        db.add(AdmissionDeposit(
            admission_id=admission.id, amount=body.deposit_amount, payment_method=body.deposit_payment_method,
            note="Initial deposit at admission", collected_by=current_doctor.id,
        ))
    db.commit()
    return {"id": admission.public_token, "message": "Patient admitted"}


@router.post("/referrals")
def send_to_admission(body: SendToAdmissionIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["doctor", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Only a doctor can send a patient for admission")

    patient = db.query(Patient).filter(Patient.id == body.patient_id, Patient.hospital_id == current_doctor.hospital_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    already_admitted = db.query(Admission).filter(Admission.patient_id == patient.id, Admission.status == "admitted").first()
    if already_admitted:
        raise HTTPException(status_code=400, detail="This patient is already admitted")

    existing = db.query(AdmissionReferral).filter(
        AdmissionReferral.patient_id == patient.id, AdmissionReferral.status == "pending"
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="This patient has already been sent for admission")

    referral = AdmissionReferral(
        hospital_id=current_doctor.hospital_id, patient_id=patient.id,
        referred_by=current_doctor.id, reason=body.reason,
    )
    db.add(referral)
    db.commit()
    return {"message": f"{patient.name} sent to reception for admission"}


@router.get("/referrals")
def list_referrals(current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    """Reception's '+ Admit' list — ONLY patients a doctor has actually sent."""
    referrals = db.query(AdmissionReferral).filter(
        AdmissionReferral.hospital_id == current_doctor.hospital_id, AdmissionReferral.status == "pending"
    ).order_by(AdmissionReferral.created_at.desc()).all()

    out = []
    for r in referrals:
        patient = db.query(Patient).filter(Patient.id == r.patient_id).first()
        doctor = db.query(Doctor).filter(Doctor.id == r.referred_by).first()
        if not patient:
            continue
        out.append({
            "referral_id": r.id, "patient_id": patient.id, "patient_name": patient.name,
            "patient_uid": patient.patient_uid, "phone": patient.phone,
            "referred_by_name": f"{doctor.title} {doctor.name}" if doctor else "Unknown",
            "reason": r.reason, "created_at": r.created_at.isoformat(),
        })
    return out


@router.delete("/referrals/{referral_id}")
def cancel_referral(referral_id: int, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    r = db.query(AdmissionReferral).filter(
        AdmissionReferral.id == referral_id, AdmissionReferral.hospital_id == current_doctor.hospital_id
    ).first()
    if not r:
        raise HTTPException(status_code=404, detail="Referral not found")
    r.status = "cancelled"
    db.commit()
    return {"message": "Referral cancelled"}


@router.get("/test-catalog")
def test_catalog_for_ward(current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["doctor", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    from app.models.test_catalog import TestCatalogItem
    items = db.query(TestCatalogItem).filter(
        TestCatalogItem.hospital_id == current_doctor.hospital_id, TestCatalogItem.is_active == True
    ).order_by(TestCatalogItem.name).all()
    return [{"id": t.id, "name": t.name, "fee": t.fee, "category": t.category} for t in items]


@router.get("/medicine-forms")
def list_medicine_forms(current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["doctor", "nurse", "assistant", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    rows = db.query(HospitalMedicine.dosage_forms).filter(
        HospitalMedicine.hospital_id == current_doctor.hospital_id,
        HospitalMedicine.is_active == True,
        HospitalMedicine.dosage_forms.isnot(None),
    ).distinct().all()
    return sorted({r[0] for r in rows if r[0]})


@router.get("/medicine-catalog")
def medicine_catalog_for_ward(dosage_form: str = "", current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["doctor", "nurse", "assistant", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    query = db.query(HospitalMedicine).filter(
        HospitalMedicine.hospital_id == current_doctor.hospital_id,
        HospitalMedicine.is_active == True,
    )
    if dosage_form:
        query = query.filter(HospitalMedicine.dosage_forms == dosage_form)
    items = query.order_by(HospitalMedicine.generic_name).all()
    return [
        {
            "id": m.id,
            "display_name": f"{m.brand_name or m.generic_name}" + (f" {m.strength}" if m.strength else ""),
            "generic_name": m.generic_name,
            "strength": m.strength,
            "price": (m.price_per_pack or 0) / m.pack_size if m.billing_mode == "per_pack" and m.pack_size else (m.price or m.price_per_pack or 0),
        }
        for m in items
    ]


@router.get("/ward-types/{ward_type_id}/beds")
def list_ward_type_beds(ward_type_id: int, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    """Auto-generated bed labels (e.g. GEN-1, GEN-2...) — admin only sets the bed COUNT,
    labels/numbering are computed, never manually entered."""
    wt = db.query(AdmissionWardType).filter(
        AdmissionWardType.id == ward_type_id, AdmissionWardType.hospital_id == current_doctor.hospital_id
    ).first()
    if not wt:
        raise HTTPException(status_code=404, detail="Ward type not found")

    occupied_labels = {
        a.bed_number for a in db.query(Admission).filter(
            Admission.ward_type_id == wt.id, Admission.status == "admitted"
        ).all()
    }
    labels = _bed_labels_for_ward_type(wt)
    return [{"label": l, "occupied": l in occupied_labels} for l in labels]


@router.get("/ward-types", response_model=list[WardTypeOut])
def list_ward_types(current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    types = db.query(AdmissionWardType).filter(AdmissionWardType.hospital_id == current_doctor.hospital_id).order_by(AdmissionWardType.name).all()
    out = []
    for t in types:
        occupied = db.query(Admission).filter(Admission.ward_type_id == t.id, Admission.status == "admitted").count()
        out.append(WardTypeOut(id=t.id, name=t.name, total_beds=t.total_beds, daily_charge=t.daily_charge, default_deposit=t.default_deposit, is_icu=t.is_icu, is_ot=t.is_ot, ot_charge=t.ot_charge, category=t.category, occupied=occupied, vacant=max(t.total_beds - occupied, 0)))
    return out


@router.post("/ward-types", response_model=WardTypeOut)
def create_ward_type(body: WardTypeCreateIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    if body.total_beds < 0 or body.daily_charge < 0 or body.default_deposit < 0:
        raise HTTPException(status_code=400, detail="Values cannot be negative")
    category = (body.category or "general").strip().lower()
    if category not in VALID_WARD_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid ward category")
    wt = AdmissionWardType(hospital_id=current_doctor.hospital_id, name=body.name.strip(), total_beds=body.total_beds, daily_charge=body.daily_charge, default_deposit=body.default_deposit, is_icu=body.is_icu, is_ot=body.is_ot, ot_charge=body.ot_charge, category=category)
    db.add(wt)
    db.commit()
    db.refresh(wt)
    return WardTypeOut(id=wt.id, name=wt.name, total_beds=wt.total_beds, daily_charge=wt.daily_charge, default_deposit=wt.default_deposit, is_icu=wt.is_icu, is_ot=wt.is_ot, ot_charge=wt.ot_charge, category=wt.category, occupied=0, vacant=wt.total_beds)


@router.put("/ward-types/{ward_type_id}", response_model=WardTypeOut)
def update_ward_type(ward_type_id: int, body: WardTypeCreateIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    wt = db.query(AdmissionWardType).filter(AdmissionWardType.id == ward_type_id, AdmissionWardType.hospital_id == current_doctor.hospital_id).first()
    if not wt:
        raise HTTPException(status_code=404, detail="Ward type not found")
    if body.total_beds < 0 or body.daily_charge < 0 or body.default_deposit < 0:
        raise HTTPException(status_code=400, detail="Values cannot be negative")
    occupied = db.query(Admission).filter(Admission.ward_type_id == wt.id, Admission.status == "admitted").count()
    if body.total_beds < occupied:
        raise HTTPException(status_code=400, detail=f"Cannot set total beds below {occupied} — that many are currently occupied")
    category = (body.category or "general").strip().lower()
    if category not in VALID_WARD_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid ward category")
    wt.name = body.name.strip()
    wt.total_beds = body.total_beds
    wt.daily_charge = body.daily_charge
    wt.default_deposit = body.default_deposit
    wt.is_icu = body.is_icu
    wt.is_ot = body.is_ot
    wt.ot_charge = body.ot_charge
    wt.category = category
    db.commit()
    return WardTypeOut(id=wt.id, name=wt.name, total_beds=wt.total_beds, daily_charge=wt.daily_charge, default_deposit=wt.default_deposit, is_icu=wt.is_icu, is_ot=wt.is_ot, ot_charge=wt.ot_charge, category=wt.category, occupied=occupied, vacant=max(wt.total_beds - occupied, 0))


@router.delete("/ward-types/{ward_type_id}")
def delete_ward_type(ward_type_id: int, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    wt = db.query(AdmissionWardType).filter(AdmissionWardType.id == ward_type_id, AdmissionWardType.hospital_id == current_doctor.hospital_id).first()
    if not wt:
        raise HTTPException(status_code=404, detail="Ward type not found")
    in_use = db.query(Admission).filter(Admission.ward_type_id == wt.id, Admission.status == "admitted").count()
    if in_use > 0:
        raise HTTPException(status_code=400, detail=f"Cannot delete — {in_use} patient(s) currently admitted under this ward type")
    db.delete(wt)
    db.commit()
    return {"message": "Ward type deleted"}


@router.get("/active")
def list_active_admissions(search: str = "", ward_type_id: int = None, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    query = db.query(Admission).filter(
        Admission.hospital_id == current_doctor.hospital_id, Admission.status == "admitted"
    )
    if ward_type_id:
        query = query.filter(Admission.ward_type_id == ward_type_id)
    admissions = query.order_by(Admission.admission_date.desc()).all()

    out = []
    for a in admissions:
        p = db.query(Patient).filter(Patient.id == a.patient_id).first()
        if search:
            q = search.lower()
            haystack = " ".join(filter(None, [p.name if p else "", p.phone if p else "", p.patient_uid if p else "", a.diagnosis or ""])).lower()
            if q not in haystack:
                continue
        out.append({
            "id": a.public_token, "patient_id": a.patient_id, "patient_name": p.name if p else "Unknown",
            "patient_uid": p.patient_uid if p else None, "phone": p.phone if p else None,
            "ward": a.ward, "bed_number": a.bed_number, "diagnosis": a.diagnosis,
            "status": a.status, "admission_date": a.admission_date.isoformat(), "days_admitted": _days_admitted(a),
        })
    return out


@router.get("/{admission_id}")
def get_admission(admission_id: str, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    patient = db.query(Patient).filter(Patient.id == a.patient_id).first()
    doctor = db.query(Doctor).filter(Doctor.id == a.admitting_doctor_id).first()

    meds = db.query(AdmissionMedicationOrder).filter(AdmissionMedicationOrder.admission_id == a.id).order_by(AdmissionMedicationOrder.created_at.desc()).all()
    med_out = []
    for m in meds:
        doses = db.query(AdmissionMedicationAdministration).filter(AdmissionMedicationAdministration.order_id == m.id).order_by(AdmissionMedicationAdministration.administered_at.desc()).all()
        returned_qty = sum(r.quantity for r in db.query(AdmissionMedicationReturn).filter(AdmissionMedicationReturn.order_id == m.id).all())
        med_out.append({
            "id": m.id, "medicine_name": m.medicine_name, "dosage": m.dosage, "route": m.route,
            "frequency_note": m.frequency_note, "is_active": m.is_active, "sourced_outside": m.sourced_outside,
            "doses": [{"id": d.id, "administered_at": d.administered_at.isoformat(), "notes": d.notes} for d in doses],
            "returned_quantity": returned_qty,
        })

    charges = db.query(AdmissionCharge).filter(AdmissionCharge.admission_id == a.id).order_by(AdmissionCharge.charged_at.desc()).all()
    charges_out = [{"id": c.id, "charge_type": c.charge_type, "description": c.description, "amount": c.amount, "quantity": c.quantity, "charged_at": c.charged_at.isoformat()} for c in charges]

    tests = db.query(TestOrder).filter(TestOrder.admission_id == a.id).order_by(TestOrder.created_at.desc()).all()
    tests_out = [{
        "id": t.id, "test_name": t.test_name, "status": t.status, "price": t.price,
        "queued_at": t.queued_at.isoformat() if t.queued_at else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        "verified_at": t.verified_at.isoformat() if t.verified_at else None,
    } for t in tests]

    charge_total = sum(c.amount * c.quantity for c in charges)
    room_breakdown, room_total = _room_charge_breakdown(db, a)
    # grand_total below is computed off the actual billable (payable_here) items via the
    # same _build_discharge_bill/apply_gst path used at real discharge, so this running
    # total always matches what the discharge invoice will actually charge, tax included.
    billable_items, _pretax_payable_total = _build_discharge_bill(db, a)
    hospital_for_gst = db.query(Hospital).filter(Hospital.id == a.hospital_id).first()
    _, gst_subtotal, gst_amount, gst_grand_total = apply_gst(billable_items, hospital_for_gst)
    professional_fee_item = next((i for i in billable_items if i["type"] == "professional_fee"), None)

    return {
        "id": a.public_token, "status": a.status, "ward": a.ward, "bed_number": a.bed_number,
        "diagnosis": a.diagnosis, "daily_room_charge": _current_daily_rate(db, a),
        "admission_date": a.admission_date.isoformat(), "discharge_date": a.discharge_date.isoformat() if a.discharge_date else None,
        "days_admitted": _days_admitted(a), "discharge_summary": a.discharge_summary,
        "discharge_type": a.discharge_type, "capacity_evaluation_note": a.capacity_evaluation_note,
        "time_of_death": a.time_of_death.isoformat() if a.time_of_death else None,
        "certifying_doctor_id": a.certifying_doctor_id, "cause_of_death": a.cause_of_death, "is_mlc": a.is_mlc,
        "discharge_order_at": a.discharge_order_at.isoformat() if a.discharge_order_at else None,
        "discharge_ordered_by_name": (lambda d: f"{d.title} {d.name}" if d else None)(db.query(Doctor).filter(Doctor.id == a.discharge_ordered_by).first()) if a.discharge_ordered_by else None,
        "discharging_doctor_id": a.discharging_doctor_id,
        "course_in_hospital": a.course_in_hospital, "procedures_performed": a.procedures_performed,
        "discharge_diagnosis": a.discharge_diagnosis, "condition_at_discharge": a.condition_at_discharge,
        "medications_on_discharge": a.medications_on_discharge, "follow_up_instructions": a.follow_up_instructions,
        "discharge_invoice_id": a.discharge_invoice_id,
        "patient": {"id": patient.id, "name": patient.name, "age": patient.age, "gender": patient.gender, "phone": patient.phone, "patient_uid": patient.patient_uid} if patient else None,
        "admitting_doctor_name": f"{doctor.title} {doctor.name}" if doctor else None,
        "admission_type": a.admission_type,
        "professional_fee_override": a.professional_fee_override,
        "professional_fee_default": doctor.professional_fee_per_admission if doctor else None,
        "medications": med_out,
        "charges": charges_out,
        "tests": tests_out,
        "bill": {
            "room_total": room_total, "room_breakdown": room_breakdown, "charges_total": charge_total,
            "professional_fee": professional_fee_item["line_total"] if professional_fee_item else 0,
            "professional_fee_label": professional_fee_item["name"] if professional_fee_item else None,
            "subtotal": gst_subtotal, "gst_total": gst_amount, "grand_total": gst_grand_total,
        }
    }


@router.get("/token-for/{admission_id}")
def token_for_admission(admission_id: int, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    """Used by the notification bell to deep-link a ward_change_request into admission-detail.html,
    which is addressed by public_token rather than the internal id carried on the notification."""
    a = db.query(Admission).filter(Admission.id == admission_id, Admission.hospital_id == current_doctor.hospital_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Admission not found")
    return {"token": a.public_token}


@router.post("/{admission_id}/request-ward-change")
def request_ward_change(admission_id: str, body: RequestWardChangeIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    """Doctor or nurse flags that a patient should be moved to a different ward — this only
    notifies reception, it does not move anyone. Reception makes the actual change via /change-ward."""
    if current_doctor.role.value not in ["doctor", "nurse", "assistant", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    if a.status != "admitted":
        raise HTTPException(status_code=400, detail="Patient is not currently admitted")
    ward_type = db.query(AdmissionWardType).filter(
        AdmissionWardType.id == body.requested_ward_type_id, AdmissionWardType.hospital_id == current_doctor.hospital_id
    ).first()
    if not ward_type:
        raise HTTPException(status_code=404, detail="Ward type not found")
    patient = db.query(Patient).filter(Patient.id == a.patient_id).first()
    notify_ward_change_request(
        db, hospital_id=current_doctor.hospital_id, admission_id=a.id,
        patient_name=patient.name if patient else "Unknown patient",
        requested_ward_name=ward_type.name,
        requested_by_name=f"{current_doctor.title} {current_doctor.name}",
        note=body.note,
    )
    db.commit()
    return {"message": "Reception has been notified"}


@router.post("/{admission_id}/change-ward")
def change_ward(admission_id: str, body: ChangeWardIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    """Reception/admin actually moves the patient: closes the current ward-stay segment and
    opens a new one at the new ward's rate. Vacancy counts update automatically since they're
    computed live from Admission.ward_type_id, which this also updates."""
    if current_doctor.role.value not in ["receptionist", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    if a.status != "admitted":
        raise HTTPException(status_code=400, detail="Patient is not currently admitted")

    new_ward_type = db.query(AdmissionWardType).filter(
        AdmissionWardType.id == body.ward_type_id, AdmissionWardType.hospital_id == current_doctor.hospital_id
    ).first()
    if not new_ward_type:
        raise HTTPException(status_code=404, detail="Ward type not found")
    if new_ward_type.id == a.ward_type_id:
        raise HTTPException(status_code=400, detail="Patient is already in this ward")

    occupied_labels = {
        a.bed_number for a in db.query(Admission).filter(
            Admission.ward_type_id == new_ward_type.id, Admission.status == "admitted"
        ).all()
    }
    if len(occupied_labels) >= new_ward_type.total_beds:
        raise HTTPException(status_code=400, detail=f"No beds available in {new_ward_type.name}")
    valid_labels = set(_bed_labels_for_ward_type(new_ward_type))
    if not body.bed_number or body.bed_number not in valid_labels:
        raise HTTPException(status_code=400, detail="Please select a valid bed")
    if body.bed_number in occupied_labels:
        raise HTTPException(status_code=400, detail=f"Bed {body.bed_number} is already occupied — pick another")

    now = now_ist_naive()
    current_stay = db.query(AdmissionWardStay).filter(
        AdmissionWardStay.admission_id == a.id, AdmissionWardStay.end_date.is_(None)
    ).order_by(AdmissionWardStay.start_date.desc()).first()
    if current_stay:
        current_stay.end_date = now
    else:
        # Legacy admission with no segments yet — close out its implied first segment now.
        db.add(AdmissionWardStay(
            admission_id=a.id, ward_type_id=a.ward_type_id, ward_name=a.ward, bed_number=a.bed_number,
            daily_charge=_current_daily_rate(db, a), start_date=a.admission_date, end_date=now,
        ))

    db.add(AdmissionWardStay(
        admission_id=a.id, ward_type_id=new_ward_type.id, ward_name=new_ward_type.name,
        bed_number=body.bed_number, daily_charge=new_ward_type.daily_charge, start_date=now,
        changed_by=current_doctor.id,
    ))

    a.ward_type_id = new_ward_type.id
    a.ward = new_ward_type.name
    a.bed_number = body.bed_number
    a.daily_room_charge = new_ward_type.daily_charge

    if new_ward_type.is_ot and new_ward_type.ot_charge:
        # Same "someone has to remember" gap as doctor-visit charges, closed
        # the same way — OT usage bills itself the moment the patient
        # actually moves into an OT-tagged segment.
        db.add(AdmissionCharge(
            admission_id=a.id, charge_type="other",
            description=f"OT Charge — {new_ward_type.name}",
            amount=new_ward_type.ot_charge, quantity=1, added_by=current_doctor.id, charged_at=now,
        ))

    db.commit()
    return {"message": f"Moved to {new_ward_type.name}"}


# ---------- Medications (MAR) ----------

@router.post("/{admission_id}/medications")
def add_medication_order(admission_id: str, body: AddMedicationOrderIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["doctor", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Only a doctor can order medications")
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    if a.status != "admitted":
        raise HTTPException(status_code=400, detail="Cannot add medications to a discharged admission")

    order = AdmissionMedicationOrder(
        admission_id=a.id, medicine_id=body.medicine_id, medicine_name=body.medicine_name,
        dosage=body.dosage, route=body.route, frequency_note=body.frequency_note,
        prescribed_by=current_doctor.id,
    )
    db.add(order)

    if not order.sourced_outside:
        patient = db.query(Patient).filter(Patient.id == a.patient_id).first()
        db.add(Notification(
            hospital_id=a.hospital_id,
            source_key=f"admission_medicine_order:{a.id}:{now_ist_naive().isoformat()}",
            type="admission_medicine_order", severity="info",
            title=f"Medicine ordered — {patient.name if patient else 'patient'}",
            message=f"{body.medicine_name} ({body.dosage}) ordered for {a.ward}, Bed {a.bed_number}.",
            link_type="admission_medicine_order", link_id=a.id, is_read=False,
        ))

    db.commit()
    db.refresh(order)
    return {"id": order.id, "message": "Medication order added"}


@router.post("/{admission_id}/medications/{order_id}/administer")
def administer_dose(admission_id: str, order_id: int, body: AdministerDoseIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["doctor", "nurse"]:
        raise HTTPException(status_code=403, detail="Only a doctor or nurse can log a dose")
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    order = db.query(AdmissionMedicationOrder).filter(AdmissionMedicationOrder.id == order_id, AdmissionMedicationOrder.admission_id == a.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Medication order not found")
    if not order.is_active:
        raise HTTPException(status_code=400, detail="This medication order has been stopped")

    admin_row = AdmissionMedicationAdministration(order_id=order.id, administered_by=current_doctor.id, administered_at=now_ist_naive(), notes=body.notes)
    db.add(admin_row)

    # If the family is sourcing this medicine themselves, still log the dose for
    # the clinical record, but skip stock deduction and billing entirely.
    if not order.sourced_outside:
        unit_price = 0.0
        if order.medicine_id:
            medicine = db.query(HospitalMedicine).filter(HospitalMedicine.id == order.medicine_id).first()
            if medicine:
                deduct_stock_fefo(db, order.medicine_id, 1, round_to_pack=False)
                if medicine.billing_mode == "per_pack" and medicine.pack_size:
                    unit_price = (medicine.price_per_pack or 0) / medicine.pack_size
                else:
                    unit_price = medicine.price or medicine.price_per_pack or 0

        db.add(AdmissionCharge(
            admission_id=a.id, charge_type="medicine",
            description=f"{order.medicine_name} ({order.dosage}) — dose given",
            amount=unit_price, quantity=1, added_by=current_doctor.id, charged_at=now_ist_naive(),
        ))
    db.commit()
    return {"message": "Dose logged"}


@router.patch("/{admission_id}/medications/{order_id}/stop")
def stop_medication(admission_id: str, order_id: int, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["doctor", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Only a doctor can stop a medication")
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    order = db.query(AdmissionMedicationOrder).filter(AdmissionMedicationOrder.id == order_id, AdmissionMedicationOrder.admission_id == a.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Medication order not found")
    order.is_active = False
    db.commit()
    return {"message": "Medication stopped"}


@router.patch("/{admission_id}/medications/{order_id}/resume")
def resume_medication(admission_id: str, order_id: int, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["doctor", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Only a doctor can resume a medication")
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    if a.status != "admitted":
        raise HTTPException(status_code=400, detail="Cannot resume medications on a discharged admission")
    order = db.query(AdmissionMedicationOrder).filter(AdmissionMedicationOrder.id == order_id, AdmissionMedicationOrder.admission_id == a.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Medication order not found")
    order.is_active = True
    db.commit()
    return {"message": "Medication resumed"}


@router.post("/{admission_id}/medications/{order_id}/return")
def return_medication(admission_id: str, order_id: int, body: ReturnMedicationIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["doctor", "nurse", "assistant"]:
        raise HTTPException(status_code=403, detail="Only a doctor, nurse, or assistant can record a medicine return")
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    if a.status != "admitted":
        raise HTTPException(status_code=400, detail="Returns can only be recorded before discharge")
    order = db.query(AdmissionMedicationOrder).filter(AdmissionMedicationOrder.id == order_id, AdmissionMedicationOrder.admission_id == a.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Medication order not found")
    if body.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than zero")

    doses_given = db.query(AdmissionMedicationAdministration).filter(AdmissionMedicationAdministration.order_id == order.id).count()
    already_returned = sum(r.quantity for r in db.query(AdmissionMedicationReturn).filter(AdmissionMedicationReturn.order_id == order.id).all())
    available_to_return = doses_given - already_returned
    if body.quantity > available_to_return:
        raise HTTPException(status_code=400, detail=f"Only {available_to_return} unit(s) from this order are eligible for return")

    if body.disposition not in ("returned_to_supplier", "sent_to_disposal", "restocked_to_shelf"):
        raise HTTPException(status_code=400, detail="disposition must be 'returned_to_supplier', 'sent_to_disposal', or 'restocked_to_shelf'")

    unit_price = 0.0
    if order.medicine_id:
        medicine = db.query(HospitalMedicine).filter(HospitalMedicine.id == order.medicine_id).first()
        if medicine:
            if medicine.billing_mode == "per_pack" and medicine.pack_size:
                unit_price = (medicine.price_per_pack or 0) / medicine.pack_size
            else:
                unit_price = medicine.price or medicine.price_per_pack or 0
            # Stock only ever moves back up on the explicit, deliberate
            # restocked_to_shelf choice — never as a default, never for the
            # other two dispositions.
            if body.disposition == "restocked_to_shelf":
                medicine.stock_quantity = (medicine.stock_quantity or 0) + body.quantity

    credit_charge = AdmissionCharge(
        admission_id=a.id, charge_type="medicine",
        description=f"{order.medicine_name} ({order.dosage}) — {body.quantity} returned ({body.disposition})",
        amount=-unit_price, quantity=body.quantity, added_by=current_doctor.id, charged_at=now_ist_naive(),
    )
    db.add(credit_charge)
    db.flush()

    db.add(AdmissionMedicationReturn(
        admission_id=a.id, order_id=order.id, quantity=body.quantity, restocked=(body.disposition == "restocked_to_shelf"), disposition=body.disposition,
        note=body.note, credit_charge_id=credit_charge.id, returned_by=current_doctor.id, returned_at=now_ist_naive(),
    ))
    db.commit()
    return {"message": "Return recorded", "credited_amount": unit_price * body.quantity}


# ---------- Charges (manual: procedures, misc) ----------

@router.post("/{admission_id}/charges")
def add_charge(admission_id: str, body: AddChargeIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["receptionist", "nurse", "assistant", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Only reception, nurse, or assistant can add charges to the bill")
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    if a.status != "admitted":
        raise HTTPException(status_code=400, detail="Cannot add charges to a discharged admission")
    charge = AdmissionCharge(
        admission_id=a.id, charge_type=body.charge_type, description=body.description,
        amount=body.amount, quantity=body.quantity, added_by=current_doctor.id, charged_at=now_ist_naive(),
    )
    db.add(charge)
    db.commit()
    return {"message": "Charge added"}


@router.post("/{admission_id}/log-visit")
def log_doctor_visit(admission_id: str, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    """Doctor-visit charges currently only existed via the generic 'Other
    Charges' free-text mechanism, which someone had to remember to use —
    unlike medicine/tests/bed-night, which accrue automatically. This is a
    one-tap action that auto-creates the charge at the doctor's own
    configured per-visit fee, closing that gap."""
    if current_doctor.role.value not in ["doctor", "nurse", "assistant", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    if a.status != "admitted":
        raise HTTPException(status_code=400, detail="Cannot log a visit for a discharged admission")

    # A doctor logs their own visit; nurse/assistant/admin log on behalf of
    # the admitting doctor, since that's whose visit fee actually applies.
    visiting_doctor = current_doctor if current_doctor.role.value == "doctor" else db.query(Doctor).filter(Doctor.id == a.admitting_doctor_id).first()
    if not visiting_doctor:
        raise HTTPException(status_code=400, detail="No treating doctor on this admission to log a visit for")
    if not visiting_doctor.visit_fee:
        raise HTTPException(status_code=400, detail=f"{visiting_doctor.title} {visiting_doctor.name} has no per-visit fee configured — set one in doctor settings first")

    charge = AdmissionCharge(
        admission_id=a.id, charge_type="other",
        description=f"Doctor Visit — {visiting_doctor.title} {visiting_doctor.name}",
        amount=visiting_doctor.visit_fee, quantity=1, added_by=current_doctor.id, charged_at=now_ist_naive(),
    )
    db.add(charge)
    db.commit()
    return {"message": "Visit logged", "amount": visiting_doctor.visit_fee}


@router.patch("/{admission_id}/professional-fee")
def update_professional_fee(admission_id: str, body: ProfessionalFeeIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    """Sets a negotiated per-admission override of the treating doctor's
    professional fee — null clears it back to the doctor's own default."""
    if current_doctor.role.value not in ["doctor", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Only the treating doctor or an admin can set the professional fee")
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    if a.status != "admitted":
        raise HTTPException(status_code=400, detail="Cannot edit charges for a discharged admission")
    if body.amount is not None and body.amount < 0:
        raise HTTPException(status_code=400, detail="Amount cannot be negative")
    a.professional_fee_override = body.amount
    db.commit()
    return {"message": "Professional fee updated", "professional_fee_override": a.professional_fee_override}


@router.post("/{admission_id}/consents")
def add_admission_consent(admission_id: str, body: AdmissionConsentIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    if body.consent_type not in VALID_CONSENT_TYPES:
        raise HTTPException(status_code=400, detail="Invalid consent type")
    if not (body.signer_name or "").strip():
        raise HTTPException(status_code=400, detail="Signer name is required")
    if body.signed_by_guardian and not (body.relationship or "").strip():
        raise HTTPException(status_code=400, detail="Relationship is required when signed on the patient's behalf")

    consent = AdmissionConsent(
        admission_id=a.id, consent_type=body.consent_type,
        signer_name=body.signer_name.strip(), signed_by_guardian=body.signed_by_guardian,
        relationship=(body.relationship or "").strip() or None,
        witness_name=(body.witness_name or "").strip() or None,
        notes=(body.notes or "").strip() or None,
        recorded_by=current_doctor.id,
    )
    db.add(consent)
    db.commit()
    db.refresh(consent)
    log_action(db, current_doctor, action="consent_recorded", target_type="admission", target_id=a.id,
               target_label=f"{body.consent_type} consent", details=f"Signed by {consent.signer_name}" + (f" ({consent.relationship})" if consent.relationship else ""))
    return {"message": "Consent recorded", "id": consent.id}


@router.get("/{admission_id}/consents")
def list_admission_consents(admission_id: str, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    consents = db.query(AdmissionConsent).filter(AdmissionConsent.admission_id == a.id).order_by(AdmissionConsent.signed_at.desc()).all()
    return [{
        "id": c.id, "consent_type": c.consent_type, "signer_name": c.signer_name,
        "signed_by_guardian": c.signed_by_guardian, "relationship": c.relationship,
        "witness_name": c.witness_name, "notes": c.notes,
        "signed_at": c.signed_at.isoformat() if c.signed_at else None,
    } for c in consents]


@router.post("/{admission_id}/discharge-order")
def place_discharge_order(admission_id: str, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    """Records when a doctor clinically decides/orders discharge — distinct
    from the actual moment the patient leaves (Admission.discharge_date,
    set by discharge_patient). The gap between the two is the
    discharge-order-to-actual-departure metric; nothing reports on it yet,
    this just makes sure the data exists. Re-callable — a later call just
    updates the timestamp (e.g. if the order needs to be re-confirmed)."""
    if current_doctor.role.value not in ["doctor", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Only a doctor can place a discharge order")
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    if a.status != "admitted":
        raise HTTPException(status_code=400, detail="This patient is not currently admitted")
    a.discharge_order_at = now_ist_naive()
    a.discharge_ordered_by = current_doctor.id
    db.commit()
    return {"message": "Discharge order placed", "discharge_order_at": a.discharge_order_at.isoformat()}


@router.post("/{admission_id}/emergency-alert")
def raise_emergency_alert(admission_id: str, body: EmergencyAlertIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    # Any staff on this hospital can raise it — deliberately no role gate
    # beyond hospital membership, since urgency shouldn't wait on a permissions check.
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    if a.status != "admitted":
        raise HTTPException(status_code=400, detail="This patient is not currently admitted")
    patient = db.query(Patient).filter(Patient.id == a.patient_id).first()
    notify_emergency_alert(
        db, hospital_id=a.hospital_id, admission_id=a.id,
        patient_name=patient.name if patient else "patient",
        doctor_id=a.admitting_doctor_id,
        raised_by_name=f"{current_doctor.title} {current_doctor.name}",
        ward=a.ward, bed_number=a.bed_number,
        message=body.message,
    )

    # If the paged doctor is mid-OPD-consultation right now, pull them out of
    # rotation and hold the queue — the exact draft they left is already
    # pinned via active_consultation_id, so nothing to guess on return.
    if a.admitting_doctor_id:
        from app.routers.attendance import set_away_for_emergency
        target_doctor = db.query(Doctor).filter(Doctor.id == a.admitting_doctor_id).first()
        if target_doctor and target_doctor.active_consultation_id:
            set_away_for_emergency(db, target_doctor.id, target_doctor.hospital_id)

    db.commit()
    return {"message": "Emergency alert sent"}


# ---------- Tests during admission ----------

@router.post("/{admission_id}/tests")
def order_admission_test(admission_id: str, body: AddAdmissionTestIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["doctor", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Only a doctor can order tests")
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    if a.status != "admitted":
        raise HTTPException(status_code=400, detail="Cannot order tests for a discharged admission")

    valid_priorities = {"routine", "urgent", "stat"}
    priority = body.priority if body.priority in valid_priorities else "routine"
    test = TestOrder(
        admission_id=a.id, patient_id=a.patient_id, hospital_id=a.hospital_id,
        test_id=body.test_id, test_name=body.test_name, price=body.price,
        included=False, status="paid",  # billed at discharge, so it can go straight to the lab queue
        paid_at=now_ist_naive(), queued_at=now_ist_naive(),
        priority=priority,
        clinical_indication=(body.clinical_indication or "").strip() or None,
    )
    db.add(test)
    db.add(AdmissionCharge(
        admission_id=a.id, charge_type="test", description=body.test_name,
        amount=body.price, quantity=1, added_by=current_doctor.id, charged_at=now_ist_naive(),
    ))

    patient = db.query(Patient).filter(Patient.id == a.patient_id).first()
    db.add(Notification(
        hospital_id=a.hospital_id,
        source_key=f"admission_test_sample:{test.id}",
        type="admission_test_sample",
        severity="info",
        title="Sample Collection Needed — Ward",
        message=f"{body.test_name} ordered for {patient.name if patient else 'patient'} — collect from {a.ward}, Bed {a.bed_number}.",
        link_type="admission_test",
        link_id=test.id,
    ))
    db.commit()
    return {"message": "Test ordered"}


# ---------- Discharge ----------

def _build_discharge_bill(db: Session, a: Admission):
    charges = db.query(AdmissionCharge).filter(AdmissionCharge.admission_id == a.id).all()
    current_rate = _current_daily_rate(db, a)
    ward_type = db.query(AdmissionWardType).filter(AdmissionWardType.id == a.ward_type_id).first() if a.ward_type_id else None
    items = []
    if a.admission_type != "day_care":
        # Day-care/short-stay never accrues overnight bed-night charges.
        items.append({"type": "room", "name": f"Room charges — {a.ward}, Bed {a.bed_number} ({_days_admitted(a)} day(s))",
                      "qty": _days_admitted(a), "unit_price": current_rate, "line_total": _days_admitted(a) * current_rate, "payable_here": True,
                      "_is_icu": bool(ward_type and ward_type.is_icu)})

    # Doctor's own professional/consultant fee — distinct from the facility
    # charge above (room, nursing, equipment). Only appears if the admitting
    # doctor has one configured, or this admission has a negotiated
    # override — most in-house/salaried doctors won't have either, this is
    # aimed at visiting/empanelled consultants. Reflects care actually
    # rendered by this doctor to this patient only — never a
    # referral/commission amount.
    prof_fee = a.professional_fee_override
    admitting_doctor = db.query(Doctor).filter(Doctor.id == a.admitting_doctor_id).first()
    if prof_fee is None and admitting_doctor:
        prof_fee = admitting_doctor.professional_fee_per_admission
    if prof_fee:
        doctor_label = f"{admitting_doctor.title} {admitting_doctor.name}" if admitting_doctor else "Treating Doctor"
        items.append({"type": "professional_fee", "name": f"Doctor Professional Fee — {doctor_label}",
                      "qty": 1, "unit_price": prof_fee, "line_total": prof_fee, "payable_here": True})

    for c in charges:
        # Pharmacy (medicine) charges are settled only at the pharmacy counter, never at
        # reception — still listed here as a reference so the total bill picture is visible.
        payable_here = c.charge_type != "medicine"
        name = c.description if payable_here else f"{c.description} (Settled at Pharmacy Counter — not included in this total)"
        items.append({"type": c.charge_type, "name": name, "qty": c.quantity, "unit_price": c.amount, "line_total": c.amount * c.quantity, "payable_here": payable_here})
    grand_total = sum(i["line_total"] for i in items if i["payable_here"])
    return items, grand_total


def _deposit_total(db: Session, a: Admission) -> float:
    return sum(d.amount for d in db.query(AdmissionDeposit).filter(AdmissionDeposit.admission_id == a.id).all())


def _tpa_proportionate_deduction_estimate(db: Session, a: Admission, tpa_case, charges_total: float):
    """(ratio, deducted_amount) — many Indian TPA policies cap the eligible
    room category (e.g. 'up to twin-sharing'); occupying a higher category
    commonly triggers a proportionate deduction across the WHOLE claim, not
    just the room-charge difference: ratio = eligible_rate / actual_rate,
    applied to the full bill. Deliberately simple and insurer-agnostic —
    exactly which line items an insurer excludes from this varies by
    policy, so this is surfaced as a clearly-labeled ESTIMATE for staff to
    verify against the insurer's actual approval letter, never silently
    substituted for authorized_amount (which staff enters from that letter
    directly)."""
    if not tpa_case or not tpa_case.eligible_daily_rate:
        return 1.0, 0.0
    actual_rate = _current_daily_rate(db, a)
    if not actual_rate or actual_rate <= tpa_case.eligible_daily_rate:
        return 1.0, 0.0
    ratio = tpa_case.eligible_daily_rate / actual_rate
    deducted = charges_total * (1 - ratio)
    return ratio, deducted


def _settlement_summary(db: Session, a: Admission):
    """(items, subtotal, gst_total, charges_total, deposit_total, tpa_covered, balance) —
    charges_total is subtotal + gst_total (tax-inclusive, what's actually payable).
    tpa_covered is how much of the outstanding balance an approved TPA case offsets
    (capped at what's actually left after the deposit). balance > 0 means the patient
    still owes; balance < 0 means a refund is due against the deposit. TPA-covered
    money is never counted as collected from the patient — it's tracked separately
    as a receivable via AdmissionTpaCase.settlement_status, reconciled later in
    settle_tpa_case once the insurer actually pays."""
    items, _pretax_total = _build_discharge_bill(db, a)
    hospital = db.query(Hospital).filter(Hospital.id == a.hospital_id).first()
    items, subtotal, gst_total, charges_total = apply_gst(items, hospital)
    deposit_total = _deposit_total(db, a)

    tpa_covered = 0.0
    tpa_case = db.query(AdmissionTpaCase).filter(
        AdmissionTpaCase.admission_id == a.id, AdmissionTpaCase.status == "approved"
    ).order_by(AdmissionTpaCase.resolved_at.desc()).first()
    if tpa_case and tpa_case.authorized_amount:
        outstanding_before_tpa = max(charges_total - deposit_total, 0)
        tpa_covered = min(tpa_case.authorized_amount, outstanding_before_tpa)

    balance = charges_total - deposit_total - tpa_covered
    return items, subtotal, gst_total, charges_total, deposit_total, tpa_covered, balance


@router.get("/{admission_id}/deposit-summary")
def get_deposit_summary(admission_id: str, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    _, subtotal, gst_total, charges_total, deposit_total, tpa_covered, balance = _settlement_summary(db, a)
    deposits = db.query(AdmissionDeposit).filter(AdmissionDeposit.admission_id == a.id).order_by(AdmissionDeposit.collected_at).all()
    topups = db.query(AdmissionDepositTopupRequest).filter(AdmissionDepositTopupRequest.admission_id == a.id).order_by(AdmissionDepositTopupRequest.requested_at.desc()).all()
    return {
        "deposit_total": deposit_total,
        "subtotal": subtotal,
        "gst_total": gst_total,
        "charges_total": charges_total,
        "tpa_covered": tpa_covered,
        "balance": balance,
        "deposits": [
            {"id": d.id, "amount": d.amount, "payment_method": d.payment_method, "note": d.note, "collected_at": d.collected_at.isoformat() if d.collected_at else None}
            for d in deposits
        ],
        "topup_requests": [
            {"id": t.id, "requested_amount": t.requested_amount, "reason": t.reason, "status": t.status,
             "requested_at": t.requested_at.isoformat() if t.requested_at else None,
             "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None}
            for t in topups
        ],
    }


@router.post("/{admission_id}/topup-requests")
def create_topup_request(admission_id: str, body: TopupRequestIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["receptionist", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Only reception can raise a deposit top-up request")
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    if a.status != "admitted":
        raise HTTPException(status_code=400, detail="Cannot request a top-up for a discharged admission")
    if body.requested_amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero")

    req = AdmissionDepositTopupRequest(
        admission_id=a.id, requested_amount=body.requested_amount, reason=body.reason,
        requested_by=current_doctor.id,
    )
    db.add(req)

    patient = db.query(Patient).filter(Patient.id == a.patient_id).first()
    db.add(Notification(
        hospital_id=a.hospital_id,
        source_key=f"deposit_topup_request:{req.id}" if req.id else f"deposit_topup_request:{admission_id}:{now_ist_naive().isoformat()}",
        type="deposit_topup_request", severity="info",
        title="Deposit Top-up Requested",
        message=f"Rs.{body.requested_amount:.2f} top-up requested for {patient.name if patient else 'patient'} — {a.ward}, Bed {a.bed_number}.",
        link_type="admission_topup", link_id=a.id,
    ))
    db.commit()
    return {"message": "Top-up request raised", "id": req.id}


@router.post("/{admission_id}/topup-requests/{request_id}/cancel")
def cancel_topup_request(admission_id: str, request_id: int, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["receptionist", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    req = db.query(AdmissionDepositTopupRequest).filter(AdmissionDepositTopupRequest.id == request_id, AdmissionDepositTopupRequest.admission_id == a.id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Top-up request not found")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail="Only a pending request can be cancelled")
    req.status = "cancelled"
    req.resolved_at = now_ist_naive()
    db.commit()
    return {"message": "Top-up request cancelled"}


@router.post("/{admission_id}/topup-requests/{request_id}/collect")
def collect_topup_request(admission_id: str, request_id: int, body: CollectTopupIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["receptionist", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized to collect payment")
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    req = db.query(AdmissionDepositTopupRequest).filter(AdmissionDepositTopupRequest.id == request_id, AdmissionDepositTopupRequest.admission_id == a.id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Top-up request not found")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail="This request has already been resolved")
    if not body.payment_method:
        raise HTTPException(status_code=400, detail="Please select how payment was collected")

    deposit = AdmissionDeposit(
        admission_id=a.id, amount=req.requested_amount, payment_method=body.payment_method,
        note="Top-up collected", collected_by=current_doctor.id,
    )
    db.add(deposit)
    db.flush()
    req.status = "collected"
    req.deposit_id = deposit.id
    req.resolved_at = now_ist_naive()
    db.commit()
    return {"message": "Top-up collected", "amount_collected": req.requested_amount}


VALID_TPA_STATUSES = {"pending", "query_raised", "approved", "denied"}


@router.get("/{admission_id}/tpa-case")
def get_tpa_case(admission_id: str, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    case = db.query(AdmissionTpaCase).filter(AdmissionTpaCase.admission_id == a.id).order_by(AdmissionTpaCase.created_at.desc()).first()
    if not case:
        return None
    deduction_ratio, deduction_estimate = 1.0, 0.0
    if case.eligible_daily_rate and a.status == "admitted":
        items, _pretax_total = _build_discharge_bill(db, a)
        hospital = db.query(Hospital).filter(Hospital.id == a.hospital_id).first()
        _, _, _, charges_total = apply_gst(items, hospital)
        deduction_ratio, deduction_estimate = _tpa_proportionate_deduction_estimate(db, a, case, charges_total)

    return {
        "id": case.id, "insurer_name": case.insurer_name, "policy_number": case.policy_number,
        "status": case.status, "authorized_amount": case.authorized_amount,
        "room_category_eligibility": case.room_category_eligibility, "eligible_daily_rate": case.eligible_daily_rate,
        "copay_notes": case.copay_notes,
        "query_notes": case.query_notes, "created_at": case.created_at.isoformat() if case.created_at else None,
        "updated_at": case.updated_at.isoformat() if case.updated_at else None,
        "resolved_at": case.resolved_at.isoformat() if case.resolved_at else None,
        "settlement_status": case.settlement_status,
        "claim_submitted_amount": case.claim_submitted_amount,
        "claim_submitted_at": case.claim_submitted_at.isoformat() if case.claim_submitted_at else None,
        "settled_amount": case.settled_amount,
        "settled_at": case.settled_at.isoformat() if case.settled_at else None,
        "settlement_notes": case.settlement_notes,
        "deduction_ratio": deduction_ratio,
        "deduction_estimate": deduction_estimate,
    }


@router.post("/{admission_id}/tpa-case")
def create_tpa_case(admission_id: str, body: TpaCaseIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["receptionist", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    existing = db.query(AdmissionTpaCase).filter(
        AdmissionTpaCase.admission_id == a.id, AdmissionTpaCase.status.in_(["pending", "query_raised"])
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="An open TPA case already exists for this admission")
    if not body.insurer_name.strip():
        raise HTTPException(status_code=400, detail="Insurer name is required")

    case = AdmissionTpaCase(
        admission_id=a.id, hospital_id=a.hospital_id, insurer_name=body.insurer_name.strip(),
        policy_number=body.policy_number, room_category_eligibility=body.room_category_eligibility,
        eligible_daily_rate=body.eligible_daily_rate,
        copay_notes=body.copay_notes, created_by=current_doctor.id,
    )
    db.add(case)
    db.commit()
    return {"message": "TPA case logged", "id": case.id}


@router.patch("/{admission_id}/tpa-case/{case_id}")
def update_tpa_case(admission_id: str, case_id: int, body: TpaCaseUpdateIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["receptionist", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    case = db.query(AdmissionTpaCase).filter(AdmissionTpaCase.id == case_id, AdmissionTpaCase.admission_id == a.id).first()
    if not case:
        raise HTTPException(status_code=404, detail="TPA case not found")
    if body.status not in VALID_TPA_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")

    case.status = body.status
    if body.authorized_amount is not None:
        case.authorized_amount = body.authorized_amount
    if body.room_category_eligibility is not None:
        case.room_category_eligibility = body.room_category_eligibility
    if body.eligible_daily_rate is not None:
        case.eligible_daily_rate = body.eligible_daily_rate
    if body.copay_notes is not None:
        case.copay_notes = body.copay_notes
    if body.query_notes is not None:
        case.query_notes = body.query_notes
    if body.status in ("approved", "denied"):
        case.resolved_at = now_ist_naive()
    db.commit()
    return {"message": "TPA case updated"}


@router.post("/{admission_id}/tpa-case/{case_id}/settle")
def settle_tpa_case(admission_id: str, case_id: int, body: TpaSettleIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    """Logs money actually received from the TPA — staff enters this
    manually once the insurer pays, since MedScribe doesn't integrate with
    insurers. Reconciles against what was claimed at discharge: a shortfall
    becomes a debit note against the original discharge invoice (the
    patient owes the difference); an overpayment becomes a refund + credit
    note. This can happen weeks after the admission was physically
    discharged — settlement is tracked independently of Admission.status."""
    if current_doctor.role.value not in ["receptionist", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    case = db.query(AdmissionTpaCase).filter(AdmissionTpaCase.id == case_id, AdmissionTpaCase.admission_id == a.id).first()
    if not case:
        raise HTTPException(status_code=404, detail="TPA case not found")
    if case.settlement_status != "awaiting_settlement":
        raise HTTPException(status_code=400, detail="This case has no claim awaiting settlement")
    if body.settled_amount < 0:
        raise HTTPException(status_code=400, detail="Settled amount cannot be negative")

    case.settlement_status = "settled"
    case.settled_amount = body.settled_amount
    case.settled_at = now_ist_naive()
    case.settlement_notes = (body.settlement_notes or "").strip() or None

    claimed = case.claim_submitted_amount or 0.0
    shortfall = max(claimed - body.settled_amount, 0)
    overpayment = max(body.settled_amount - claimed, 0)

    note_number = None
    if a.discharge_invoice_id:
        invoice = db.query(Invoice).filter(Invoice.id == a.discharge_invoice_id).first()
        hospital = db.query(Hospital).filter(Hospital.id == a.hospital_id).first()
        if invoice and hospital:
            if shortfall > 0:
                note = CreditDebitNote(
                    hospital_id=a.hospital_id, invoice_id=invoice.id, patient_id=invoice.patient_id,
                    note_type="debit", note_number=next_note_number(db, hospital, "debit"),
                    invoice_number=invoice.receipt_number, invoice_date=invoice.generated_at,
                    amount=shortfall, reason=f"TPA settled Rs.{body.settled_amount:.2f} against Rs.{claimed:.2f} claimed — shortfall owed by patient",
                    created_by=current_doctor.id,
                )
                db.add(note)
                db.flush()
                note_number = note.note_number
            elif overpayment > 0:
                refund = Refund(
                    patient_id=invoice.patient_id, hospital_id=a.hospital_id, source_type="tpa", source_id=case.id,
                    amount=overpayment, channel="online", status="pending",
                    reason=f"TPA settled Rs.{body.settled_amount:.2f} against Rs.{claimed:.2f} claimed — overpayment refunded to patient",
                    processed_by=current_doctor.id,
                )
                db.add(refund)
                db.flush()
                note = CreditDebitNote(
                    hospital_id=a.hospital_id, invoice_id=invoice.id, patient_id=invoice.patient_id,
                    note_type="credit", note_number=next_note_number(db, hospital, "credit"),
                    invoice_number=invoice.receipt_number, invoice_date=invoice.generated_at,
                    amount=overpayment, reason=refund.reason, refund_id=refund.id,
                    created_by=current_doctor.id,
                )
                db.add(note)
                db.flush()
                note_number = note.note_number

    db.commit()
    return {"message": "TPA settlement recorded", "shortfall": shortfall, "overpayment": overpayment, "note_number": note_number}


@router.get("/tpa-receivables")
def list_tpa_receivables(current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    """All open 'billed to TPA, awaiting settlement' cases across the
    hospital — the aggregate view finance needs, versus the per-admission
    lookup on the admission page itself."""
    if current_doctor.role.value not in ["receptionist", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    cases = db.query(AdmissionTpaCase).filter(
        AdmissionTpaCase.hospital_id == current_doctor.hospital_id,
        AdmissionTpaCase.settlement_status == "awaiting_settlement"
    ).order_by(AdmissionTpaCase.claim_submitted_at).all()

    result = []
    for c in cases:
        a = db.query(Admission).filter(Admission.id == c.admission_id).first()
        p = db.query(Patient).filter(Patient.id == a.patient_id).first() if a else None
        result.append({
            "case_id": c.id,
            "admission_id": a.public_token if a else None,
            "patient_name": p.name if p else None,
            "patient_uid": p.patient_uid if p else None,
            "insurer_name": c.insurer_name,
            "policy_number": c.policy_number,
            "claim_submitted_amount": c.claim_submitted_amount,
            "claim_submitted_at": c.claim_submitted_at.isoformat() if c.claim_submitted_at else None,
            "discharge_date": a.discharge_date.isoformat() if a and a.discharge_date else None,
        })
    return result


@router.get("/{admission_id}/discharge-preview")
def discharge_preview(admission_id: str, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    """Shows what's owed BEFORE committing discharge — reception collects this first."""
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    items, subtotal, gst_total, charges_total, deposit_total, tpa_covered, balance = _settlement_summary(db, a)
    return {
        "items": items, "subtotal": subtotal, "gst_total": gst_total, "charges_total": charges_total,
        "deposit_total": deposit_total, "tpa_covered": tpa_covered, "balance": balance,
        "amount_due": max(balance, 0), "refund_due": max(-balance, 0),
    }


@router.post("/{admission_id}/discharge")
def discharge_patient(admission_id: str, body: DischargeIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    if current_doctor.role.value not in ["receptionist", "admin", "sub_admin"]:
        raise HTTPException(status_code=403, detail="Only reception can discharge a patient")
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    if a.status != "admitted":
        raise HTTPException(status_code=400, detail="Already discharged")

    discharge_type = (body.discharge_type or "planned").strip().lower()
    if discharge_type not in VALID_DISCHARGE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid discharge type")

    if discharge_type == "lama_dama":
        if not (body.discharge_summary or "").strip():
            raise HTTPException(status_code=400, detail="A discharge summary documenting condition at time of leaving is required for LAMA/DAMA")
        lama_consent = db.query(AdmissionConsent).filter(
            AdmissionConsent.admission_id == a.id, AdmissionConsent.consent_type == "lama_dama"
        ).first()
        if not lama_consent:
            raise HTTPException(status_code=400, detail="A signed LAMA/DAMA consent-to-leave record is required before this discharge can proceed — record it under Consents first")
    elif discharge_type == "death":
        if not body.time_of_death:
            raise HTTPException(status_code=400, detail="Time of death is required")
        if not body.certifying_doctor_id:
            raise HTTPException(status_code=400, detail="Certifying doctor is required")
        if not (body.cause_of_death or "").strip():
            raise HTTPException(status_code=400, detail="Cause of death documentation is required")
        if body.is_mlc is None:
            raise HTTPException(status_code=400, detail="Please indicate whether this is a Medico-Legal Case (MLC)")

    # Billing and deposit-refund proceed exactly the same regardless of
    # discharge_type — no charge waiver for LAMA/DAMA, and for a death the
    # refund is simply routed to whichever payout details staff enter below
    # (next of kin) via the existing refund_channel flow.
    items, subtotal, gst_total, charges_total, deposit_total, tpa_covered, balance = _settlement_summary(db, a)
    amount_due = max(balance, 0)
    refund_due = max(-balance, 0)

    if amount_due > 0 and not body.payment_collected:
        raise HTTPException(status_code=402, detail=f"Payment of Rs.{amount_due:.2f} is still pending (deposit Rs.{deposit_total:.2f}{' + TPA-covered Rs.' + format(tpa_covered, '.2f') if tpa_covered > 0 else ''} vs charges Rs.{charges_total:.2f}) — collect payment before discharge can proceed")
    if body.payment_collected and not body.payment_method:
        raise HTTPException(status_code=400, detail="Please select how payment was collected")
    if refund_due > 0 and not body.refund_channel:
        raise HTTPException(status_code=400, detail=f"Deposit exceeds charges by Rs.{refund_due:.2f} — select how the refund will be paid out")

    a.status = "discharged"
    a.discharge_date = now_ist_naive()
    a.discharge_summary = body.discharge_summary
    a.discharge_type = discharge_type
    a.discharging_doctor_id = body.discharging_doctor_id or a.admitting_doctor_id
    a.course_in_hospital = (body.course_in_hospital or "").strip() or None
    a.procedures_performed = (body.procedures_performed or "").strip() or None
    a.discharge_diagnosis = (body.discharge_diagnosis or "").strip() or None
    a.condition_at_discharge = (body.condition_at_discharge or "").strip() or None
    a.medications_on_discharge = (body.medications_on_discharge or "").strip() or None
    a.follow_up_instructions = (body.follow_up_instructions or "").strip() or None
    if discharge_type == "lama_dama":
        a.capacity_evaluation_note = (body.capacity_evaluation_note or "").strip() or None
    elif discharge_type == "death":
        a.time_of_death = datetime.fromisoformat(body.time_of_death)
        a.certifying_doctor_id = body.certifying_doctor_id
        a.cause_of_death = body.cause_of_death.strip()
        a.is_mlc = body.is_mlc

    # A physical discharge can happen well before the TPA actually pays —
    # this just marks the claim as submitted/awaiting settlement; the
    # admission itself is free to be "discharged" while this stays open.
    if tpa_covered > 0:
        tpa_case = db.query(AdmissionTpaCase).filter(
            AdmissionTpaCase.admission_id == a.id, AdmissionTpaCase.status == "approved"
        ).order_by(AdmissionTpaCase.resolved_at.desc()).first()
        if tpa_case:
            tpa_case.settlement_status = "awaiting_settlement"
            tpa_case.claim_submitted_amount = tpa_covered
            tpa_case.claim_submitted_at = now_ist_naive()

    db.commit()

    patient = db.query(Patient).filter(Patient.id == a.patient_id).first()
    hospital = db.query(Hospital).filter(Hospital.id == a.hospital_id).first()

    invoice = Invoice(
        checkin_id=None, admission_id=a.id, patient_id=a.patient_id, hospital_id=a.hospital_id,
        items_json=json.dumps(items), grand_total=charges_total, subtotal=subtotal, gst_total=gst_total,
        amount_collected=amount_due,
        generated_by=current_doctor.id, generated_from="admission_discharge",
        payment_method=body.payment_method,
        receipt_number=next_receipt_number(db, hospital),
        place_of_supply=hospital.state,
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)

    admitting_doctor = db.query(Doctor).filter(Doctor.id == a.admitting_doctor_id).first()
    pdf_path = generate_invoice_pdf(invoice.id, hospital, items, charges_total, patient, admitting_doctor, receipt_number=invoice.receipt_number, place_of_supply=invoice.place_of_supply)
    invoice.pdf_path = pdf_path
    a.discharge_invoice_id = invoice.id

    if refund_due > 0:
        db.add(Refund(
            patient_id=a.patient_id, hospital_id=a.hospital_id, source_type="ipd_deposit", source_id=a.id,
            amount=refund_due, channel=body.refund_channel,
            status="pending" if body.refund_channel == "online" else "completed",
            reason="Deposit balance refund at discharge", processed_by=current_doctor.id,
        ))
    db.commit()

    return {
        "message": "Patient discharged", "invoice_id": invoice.id,
        "subtotal": subtotal, "gst_total": gst_total, "grand_total": charges_total, "deposit_total": deposit_total,
        "refund_due": refund_due,
        "amount_collected": amount_due,
    }


@router.get("/{admission_id}/invoice/pdf")
def download_discharge_invoice(admission_id: str, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    if not a.discharge_invoice_id:
        raise HTTPException(status_code=404, detail="No discharge invoice yet")
    invoice = db.query(Invoice).filter(Invoice.id == a.discharge_invoice_id).first()
    if not invoice or not invoice.pdf_path:
        raise HTTPException(status_code=404, detail="Invoice PDF not found")
    return FileResponse(invoice.pdf_path, media_type="application/pdf", filename=f"discharge_invoice_{admission_id}.pdf")