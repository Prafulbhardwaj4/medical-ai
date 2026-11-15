"""Hospital-scoped fetch helpers.

Every helper takes the caller's hospital_id and returns the row ONLY if it belongs to that hospital.
A row of another hospital looks exactly like a row that does not exist (404), so ids cannot be probed.
A user with no hospital (super_admin) gets 404, the same as the existing "hospital_id ==" filters.

Child rows are scoped through their parent admission (the parent is authoritative), never by trusting
a client-sent id or the child's own hospital_id column alone.
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.admission import (
    Admission, AdmissionMedicationOrder, AdmissionMedicationAdministration,
    AdmissionMedicationDispense, AdmissionMedicationReturn, AdmissionCharge,
)
from app.models.admission_consent import AdmissionConsent
from app.models.admission_deposit import AdmissionDeposit, AdmissionDepositTopupRequest
from app.models.admission_progress_note import AdmissionProgressNote
from app.models.admission_vitals import AdmissionVitals
from app.models.admission_ward_stay import AdmissionWardStay
from app.models.consultation import Consultation
from app.models.patient import Patient


def _not_found(what: str):
    return HTTPException(status_code=404, detail=f"{what} not found")


def _need_hospital(hospital_id, what: str):
    if not hospital_id:
        raise _not_found(what)


def get_admission(db: Session, admission_id, hospital_id) -> Admission:
    _need_hospital(hospital_id, "Admission")
    row = db.query(Admission).filter(Admission.id == admission_id, Admission.hospital_id == hospital_id).first()
    if row is None:
        raise _not_found("Admission")
    return row


def get_admission_by_token(db: Session, public_token, hospital_id) -> Admission:
    _need_hospital(hospital_id, "Admission")
    row = db.query(Admission).filter(Admission.public_token == public_token, Admission.hospital_id == hospital_id).first()
    if row is None:
        raise _not_found("Admission")
    return row


def _via_admission(db: Session, model, row_id, hospital_id, what: str):
    _need_hospital(hospital_id, what)
    row = (
        db.query(model)
        .join(Admission, model.admission_id == Admission.id)
        .filter(model.id == row_id, Admission.hospital_id == hospital_id)
        .first()
    )
    if row is None:
        raise _not_found(what)
    return row


def _via_order(db: Session, model, row_id, hospital_id, what: str):
    _need_hospital(hospital_id, what)
    row = (
        db.query(model)
        .join(AdmissionMedicationOrder, model.order_id == AdmissionMedicationOrder.id)
        .join(Admission, AdmissionMedicationOrder.admission_id == Admission.id)
        .filter(model.id == row_id, Admission.hospital_id == hospital_id)
        .first()
    )
    if row is None:
        raise _not_found(what)
    return row


def get_medication_order(db: Session, order_id, hospital_id) -> AdmissionMedicationOrder:
    return _via_admission(db, AdmissionMedicationOrder, order_id, hospital_id, "Medication order")


def get_administration(db: Session, row_id, hospital_id) -> AdmissionMedicationAdministration:
    return _via_order(db, AdmissionMedicationAdministration, row_id, hospital_id, "Dose record")


def get_dispense(db: Session, row_id, hospital_id) -> AdmissionMedicationDispense:
    return _via_order(db, AdmissionMedicationDispense, row_id, hospital_id, "Dispense record")


def get_medication_return(db: Session, row_id, hospital_id) -> AdmissionMedicationReturn:
    return _via_admission(db, AdmissionMedicationReturn, row_id, hospital_id, "Return record")


def get_charge(db: Session, charge_id, hospital_id) -> AdmissionCharge:
    return _via_admission(db, AdmissionCharge, charge_id, hospital_id, "Charge")


def get_consent(db: Session, row_id, hospital_id) -> AdmissionConsent:
    return _via_admission(db, AdmissionConsent, row_id, hospital_id, "Consent")


def get_deposit(db: Session, row_id, hospital_id) -> AdmissionDeposit:
    return _via_admission(db, AdmissionDeposit, row_id, hospital_id, "Deposit")


def get_topup_request(db: Session, row_id, hospital_id) -> AdmissionDepositTopupRequest:
    return _via_admission(db, AdmissionDepositTopupRequest, row_id, hospital_id, "Top-up request")


def get_progress_note(db: Session, row_id, hospital_id) -> AdmissionProgressNote:
    return _via_admission(db, AdmissionProgressNote, row_id, hospital_id, "Progress note")


def get_vitals(db: Session, row_id, hospital_id) -> AdmissionVitals:
    return _via_admission(db, AdmissionVitals, row_id, hospital_id, "Vitals record")


def get_ward_stay(db: Session, row_id, hospital_id) -> AdmissionWardStay:
    return _via_admission(db, AdmissionWardStay, row_id, hospital_id, "Ward stay")


def get_patient(db: Session, patient_id, hospital_id) -> Patient:
    _need_hospital(hospital_id, "Patient")
    row = db.query(Patient).filter(Patient.id == patient_id, Patient.hospital_id == hospital_id).first()
    if row is None:
        raise _not_found("Patient")
    return row


def get_consultation(db: Session, consultation_id, hospital_id) -> Consultation:
    """A consultation has no hospital of its own: it belongs to its patient's hospital."""
    _need_hospital(hospital_id, "Consultation")
    row = (
        db.query(Consultation)
        .join(Patient, Consultation.patient_id == Patient.id)
        .filter(Consultation.id == consultation_id, Patient.hospital_id == hospital_id)
        .first()
    )
    if row is None:
        raise _not_found("Consultation")
    return row


def get_consultation_by_token(db: Session, token_number, hospital_id) -> Consultation:
    _need_hospital(hospital_id, "Consultation")
    row = (
        db.query(Consultation)
        .join(Patient, Consultation.patient_id == Patient.id)
        .filter(Consultation.token_number == token_number, Patient.hospital_id == hospital_id)
        .first()
    )
    if row is None:
        raise _not_found("Consultation")
    return row