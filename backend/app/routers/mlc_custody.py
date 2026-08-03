from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.models.doctor import Doctor
from app.models.test_order import TestOrder
from app.models.patient import Patient
from app.models.mlc_custody import MlcChainOfCustody
from app.utils.auth import get_current_doctor
from app.utils.audit import log_action

router = APIRouter(prefix="/mlc-custody", tags=["mlc-custody"])

_ALLOWED_ROLES = ["doctor", "nurse", "assistant", "receptionist", "lab", "admin", "sub_admin"]
_VALID_STAGES = {
    "collected_from_patient", "handed_to_transport", "received_at_lab",
    "moved_to_storage", "processing_started", "released_to_authority", "rejected", "other",
}


class MarkMlcIn(BaseModel):
    case_type: str  # "assault" | "rta" | "poisoning" | "sexual_assault" | "other"
    reference_number: Optional[str] = None
    seal_number: Optional[str] = None
    notes: Optional[str] = None


class HandoffIn(BaseModel):
    stage: str
    handed_over_by_id: Optional[int] = None
    handed_over_by_external_name: Optional[str] = None
    received_by_id: Optional[int] = None
    received_by_external_name: Optional[str] = None
    seal_intact: bool
    seal_number: Optional[str] = None
    notes: Optional[str] = None


def _require_mlc_role(current_doctor: Doctor):
    if current_doctor.role.value not in _ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized")


def _get_order(db: Session, order_id: int, hospital_id: int) -> TestOrder:
    order = db.query(TestOrder).filter(TestOrder.id == order_id, TestOrder.hospital_id == hospital_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Test order not found")
    return order


@router.post("/{order_id}/mark")
def mark_as_mlc(
    order_id: int,
    body: MarkMlcIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    """Flags the sample as MLC and opens the chain-of-custody log with the
    first entry — collection from the patient. Idempotent on the flag
    itself, but always logs a fresh custody entry."""
    _require_mlc_role(current_doctor)
    valid_case_types = {"assault", "rta", "poisoning", "sexual_assault", "other"}
    if body.case_type not in valid_case_types:
        raise HTTPException(status_code=400, detail=f"case_type must be one of: {', '.join(valid_case_types)}")

    order = _get_order(db, order_id, current_doctor.hospital_id)
    order.is_mlc_sample = True
    order.mlc_case_type = body.case_type
    order.mlc_reference_number = body.reference_number

    db.add(MlcChainOfCustody(
        test_order_id=order.id, hospital_id=current_doctor.hospital_id,
        stage="collected_from_patient",
        handed_over_by=None, received_by=current_doctor.id,
        seal_intact=True, seal_number=body.seal_number,
        notes=body.notes, recorded_by=current_doctor.id,
    ))
    db.commit()

    log_action(
        db, current_doctor, action="mlc_sample_flagged", target_type="test_order",
        target_id=order.id, target_label=order.test_name, hospital_id=current_doctor.hospital_id,
        details=f"case_type={body.case_type}, reference={body.reference_number or '-'}"
    )
    return {"id": order.id, "is_mlc_sample": True}


@router.post("/{order_id}/handoff")
def log_handoff(
    order_id: int,
    body: HandoffIn,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    _require_mlc_role(current_doctor)
    if body.stage not in _VALID_STAGES:
        raise HTTPException(status_code=400, detail=f"stage must be one of: {', '.join(sorted(_VALID_STAGES))}")

    order = _get_order(db, order_id, current_doctor.hospital_id)
    if not order.is_mlc_sample:
        raise HTTPException(status_code=400, detail="This order isn't flagged as an MLC sample")

    db.add(MlcChainOfCustody(
        test_order_id=order.id, hospital_id=current_doctor.hospital_id,
        stage=body.stage,
        handed_over_by=body.handed_over_by_id, handed_over_by_external_name=body.handed_over_by_external_name,
        received_by=body.received_by_id, received_by_external_name=body.received_by_external_name,
        seal_intact=body.seal_intact, seal_number=body.seal_number,
        notes=body.notes, recorded_by=current_doctor.id,
    ))
    db.commit()

    log_action(
        db, current_doctor, action="mlc_custody_handoff_logged", target_type="test_order",
        target_id=order.id, target_label=order.test_name, hospital_id=current_doctor.hospital_id,
        details=f"stage={body.stage}, seal_intact={body.seal_intact}"
    )
    return {"message": "Handoff logged"}


@router.get("/{order_id}")
def get_custody_chain(
    order_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    _require_mlc_role(current_doctor)
    order = _get_order(db, order_id, current_doctor.hospital_id)

    patient = db.query(Patient).filter(Patient.id == order.patient_id).first()
    entries = db.query(MlcChainOfCustody).filter(
        MlcChainOfCustody.test_order_id == order_id
    ).order_by(MlcChainOfCustody.recorded_at.asc()).all()

    def _name(doctor_id):
        if not doctor_id:
            return None
        d = db.query(Doctor).filter(Doctor.id == doctor_id).first()
        return f"{d.title} {d.name}" if d else None

    return {
        "order_id": order.id,
        "test_name": order.test_name,
        "patient_name": patient.name if patient else "Unknown",
        "is_mlc_sample": order.is_mlc_sample,
        "case_type": order.mlc_case_type,
        "reference_number": order.mlc_reference_number,
        "chain": [{
            "stage": e.stage,
            "handed_over_by": _name(e.handed_over_by) or e.handed_over_by_external_name,
            "received_by": _name(e.received_by) or e.received_by_external_name,
            "seal_intact": e.seal_intact,
            "seal_number": e.seal_number,
            "notes": e.notes,
            "recorded_by": _name(e.recorded_by),
            "recorded_at": e.recorded_at.isoformat() if e.recorded_at else None,
        } for e in entries]
    }