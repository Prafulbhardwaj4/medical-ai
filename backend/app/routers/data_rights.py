"""Patient data rights for hospital admins (Phase 7): export, correct, anonymise.

Admin role only, and always limited to the admin's own hospital. Every call is audited.
"""
from datetime import date, datetime
from enum import Enum
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.admission import Admission
from app.models.checkin import Checkin
from app.models.consent_record import ConsentRecord
from app.models.consultation import Consultation
from app.models.doctor import Doctor
from app.models.invoice import Invoice
from app.models.patient import Patient
from app.models.patient_allergy import PatientAllergy
from app.models.portal import Appointment, PatientProfileLink
from app.models.test_order import TestOrder
from app.models.whatsapp_message import WhatsappMessage
from app.utils.audit import log_action
from app.utils.phone import normalize_phone
from app.utils.roles import require_roles

router = APIRouter(prefix="/data-rights", tags=["data-rights"])

ANON_NAME = "Anonymised Patient"
ANON_PHONE = "0000000000"
_SKIP = {"verify_hash", "url_token"}


def _plain(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def _dump(obj) -> dict:
    return {c.key: _plain(getattr(obj, c.key)) for c in sa_inspect(obj).mapper.column_attrs if c.key not in _SKIP}


def _get_patient(db: Session, admin: Doctor, patient_id: int) -> Patient:
    patient = db.query(Patient).filter(Patient.id == patient_id, Patient.hospital_id == admin.hospital_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


def _mask_abha(value) -> str:
    return f"…{value[-4:]}" if value else "empty"


# ------------------------------------------------------------------ export

@router.get("/patients/{patient_id}/export")
def export_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    admin: Doctor = Depends(require_roles("admin")),
):
    patient = _get_patient(db, admin, patient_id)
    hid = admin.hospital_id
    consultations = db.query(Consultation).filter(Consultation.patient_id == patient.id).order_by(Consultation.id).all()
    link_ids = [l.id for l in db.query(PatientProfileLink).filter(PatientProfileLink.patient_id == patient.id).all()]
    appointments = db.query(Appointment).filter(
        Appointment.profile_link_id.in_(link_ids), Appointment.hospital_id == hid
    ).all() if link_ids else []

    data = {
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "profile": _dump(patient),
        "consultations": [_dump(c) for c in consultations],
        "prescriptions": [
            {"token_number": c.token_number, "date": _plain(c.created_at), "diagnosis": c.diagnosis,
             "medicines": c.medicines, "tests": c.tests, "advice": c.advice, "followup": c.followup}
            for c in consultations if c.token_number
        ],
        "lab": [_dump(t) for t in db.query(TestOrder).filter(TestOrder.patient_id == patient.id, TestOrder.hospital_id == hid).all()],
        "invoices": [_dump(i) for i in db.query(Invoice).filter(Invoice.patient_id == patient.id, Invoice.hospital_id == hid).all()],
        "appointments": [_dump(a) for a in appointments],
        "visits": [_dump(c) for c in db.query(Checkin).filter(Checkin.patient_id == patient.id, Checkin.hospital_id == hid).all()],
        "allergies": [_dump(a) for a in db.query(PatientAllergy).filter(PatientAllergy.patient_id == patient.id, PatientAllergy.hospital_id == hid).all()],
        "consents": [_dump(c) for c in db.query(ConsentRecord).filter(
            ConsentRecord.subject_type == "patient", ConsentRecord.subject_id == patient.id).all()],
    }
    log_action(db, admin, action="patient_data_exported", target_type="patient", target_id=patient.id,
               target_label=f"{patient.name} ({patient.patient_uid})",
               details=f"{len(consultations)} consultation(s), {len(data['invoices'])} invoice(s)", hospital_id=hid)
    return data


# ----------------------------------------------------------------- correct

class CorrectIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=20)
    age: Optional[int] = Field(default=None, ge=0, le=130)
    date_of_birth: Optional[date] = None
    gender: Optional[str] = Field(default=None, max_length=20)
    blood_group: Optional[str] = Field(default=None, max_length=5)
    address: Optional[str] = Field(default=None, max_length=300)
    abha_number: Optional[str] = Field(default=None, max_length=20)


@router.put("/patients/{patient_id}/correct")
def correct_patient(
    patient_id: int,
    body: CorrectIn,
    db: Session = Depends(get_db),
    admin: Doctor = Depends(require_roles("admin")),
):
    patient = _get_patient(db, admin, patient_id)
    changes = body.dict(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing to change")
    for key in ("name", "gender"):
        if key in changes and not (changes[key] or "").strip():
            raise HTTPException(status_code=400, detail=f"{key.capitalize()} cannot be empty")
    if "phone" in changes:
        phone = normalize_phone(changes["phone"] or "")
        if not phone:
            raise HTTPException(status_code=400, detail="Phone number is not valid")
        changes["phone"] = phone
    if "abha_number" in changes:
        import re
        abha = (changes["abha_number"] or "").replace("-", "").replace(" ", "")
        if abha and not re.match(r"^[0-9]{14}$", abha):
            raise HTTPException(status_code=400, detail="ABHA number must be 14 digits")
        changes["abha_number"] = abha or None
    if "date_of_birth" in changes and changes["date_of_birth"] and "age" not in changes:
        from app.routers.patients import _age_from_dob
        changes["age"] = _age_from_dob(changes["date_of_birth"], patient.age)

    before = {k: getattr(patient, k) for k in changes}
    for key, value in changes.items():
        setattr(patient, key, value.strip() if isinstance(value, str) else value)
    db.commit()
    if "phone" in changes and before["phone"] != patient.phone:
        from app.routers.patients import _auto_link_portal_profile
        _auto_link_portal_profile(db, patient)

    def show(k, v):
        return _mask_abha(v) if k == "abha_number" else repr(v)

    lines = [f"{k}: {show(k, before[k])} -> {show(k, getattr(patient, k))}" for k in changes if before[k] != getattr(patient, k)]
    log_action(db, admin, action="patient_record_corrected", target_type="patient", target_id=patient.id,
               target_label=f"{patient.name} ({patient.patient_uid})",
               details=("; ".join(lines) or "no field changes")[:1500], hospital_id=admin.hospital_id)
    return {"corrected": True, "fields_changed": len(lines)}


# --------------------------------------------------------------- anonymise

class AnonymiseIn(BaseModel):
    confirm_text: str = Field(max_length=80)


@router.post("/patients/{patient_id}/anonymise")
def anonymise_patient(
    patient_id: int,
    body: AnonymiseIn,
    db: Session = Depends(get_db),
    admin: Doctor = Depends(require_roles("admin")),
):
    """Irreversible. Removes who the patient is; keeps invoices and clinical rows (identity stripped)."""
    patient = _get_patient(db, admin, patient_id)
    hid = admin.hospital_id
    if body.confirm_text.strip() != f"ANONYMISE {patient.patient_uid}":
        raise HTTPException(status_code=400, detail=f"Type ANONYMISE {patient.patient_uid} to confirm")

    group = {patient.id: patient}
    frontier = [patient.id]
    while frontier:
        shells = db.query(Patient).filter(Patient.hospital_id == hid, Patient.merged_into_id.in_(frontier)).all()
        frontier = [s.id for s in shells if s.id not in group]
        for s in shells:
            group[s.id] = s
    ids = list(group.keys())

    if db.query(Admission.id).filter(Admission.patient_id.in_(ids), Admission.status == "admitted").first():
        raise HTTPException(status_code=400, detail="This patient is admitted right now. Discharge them first.")

    from app.routers.patients import generate_url_token
    for p in group.values():
        p.name = ANON_NAME
        p.phone = ANON_PHONE
        p.address = None
        p.abha_number = None
        p.date_of_birth = None
        p.url_token = generate_url_token(db)
        p.is_active = False

    transcripts = db.query(Consultation).filter(
        Consultation.patient_id.in_(ids), Consultation.raw_transcript.isnot(None)
    ).update({Consultation.raw_transcript: None}, synchronize_session=False)

    messages = db.query(WhatsappMessage).filter(
        WhatsappMessage.hospital_id == hid, WhatsappMessage.recipient_kind == "patient",
        WhatsappMessage.recipient_id.in_(ids),
    ).update({WhatsappMessage.recipient_name: ANON_NAME, WhatsappMessage.recipient_phone: ANON_PHONE,
              WhatsappMessage.message_text: "[removed]", WhatsappMessage.secret_enc: None},
             synchronize_session=False)

    links = db.query(PatientProfileLink).filter(PatientProfileLink.patient_id.in_(ids)).all()
    appointments = 0
    if links:
        appointments = db.query(Appointment).filter(
            Appointment.profile_link_id.in_([l.id for l in links]), Appointment.hospital_id == hid
        ).update({Appointment.new_patient_name: None, Appointment.address: None}, synchronize_session=False)
        for account_id in {l.account_id for l in links}:
            asked = db.query(ConsentRecord.id).filter(
                ConsentRecord.subject_type == "portal_account", ConsentRecord.subject_id == account_id,
                ConsentRecord.purpose == "data_request_erasure").first()
            if asked:
                db.add(ConsentRecord(hospital_id=hid, subject_type="portal_account", subject_id=account_id,
                                     purpose="done_data_request_erasure", notice_version="done", recorded_by=admin.id))
    db.commit()

    log_action(db, admin, action="patient_anonymised", target_type="patient", target_id=patient.id,
               target_label=patient.patient_uid,
               details=(f"Irreversible. {len(ids)} record(s) anonymised ({len(ids) - 1} merged), "
                        f"{transcripts} transcript(s) cleared, {messages} message(s) cleared, {appointments} booking(s) cleared"),
               hospital_id=hid)
    return {"anonymised": True, "patient_records": len(ids)}