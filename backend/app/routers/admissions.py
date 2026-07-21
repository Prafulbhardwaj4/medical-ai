from datetime import datetime, date as date_cls

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.admission import Admission, AdmissionMedicationOrder, AdmissionMedicationAdministration, AdmissionCharge
from app.models.patient import Patient
from app.models.doctor import Doctor
from app.models.hospital import Hospital
from app.models.hospital_medicine import HospitalMedicine
from app.models.test_order import TestOrder
from app.models.invoice import Invoice
from app.schemas.admission import (
    AdmitPatientIn, AddMedicationOrderIn, AdministerDoseIn, AddChargeIn, AddAdmissionTestIn, DischargeIn
)
from app.utils.auth import get_current_doctor
from app.utils.timezone import now_ist_naive
from app.utils.inventory import deduct_stock_fefo
from app.services.pdf_service import generate_invoice_pdf
import json

router = APIRouter(prefix="/admissions", tags=["admissions"])


def _days_admitted(admission: Admission) -> int:
    end = admission.discharge_date or now_ist_naive()
    days = (end.date() - admission.admission_date.date()).days + 1
    return max(days, 1)


def _room_total(admission: Admission) -> float:
    return _days_admitted(admission) * admission.daily_room_charge


def _get_admission_or_404(db: Session, admission_id: int, hospital_id: int) -> Admission:
    a = db.query(Admission).filter(Admission.id == admission_id, Admission.hospital_id == hospital_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Admission not found")
    return a


@router.post("")
def admit_patient(body: AdmitPatientIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.id == body.patient_id, Patient.hospital_id == current_doctor.hospital_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    already_admitted = db.query(Admission).filter(Admission.patient_id == patient.id, Admission.status == "admitted").first()
    if already_admitted:
        raise HTTPException(status_code=400, detail="This patient is already admitted")

    admission = Admission(
        patient_id=patient.id, hospital_id=current_doctor.hospital_id,
        admitting_doctor_id=current_doctor.id, ward=body.ward, bed_number=body.bed_number,
        diagnosis=body.diagnosis, daily_room_charge=body.daily_room_charge,
        status="admitted", admission_date=now_ist_naive(),
    )
    db.add(admission)
    db.commit()
    db.refresh(admission)
    return {"id": admission.id, "message": "Patient admitted"}


@router.get("/active")
def list_active_admissions(current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    admissions = db.query(Admission).filter(
        Admission.hospital_id == current_doctor.hospital_id, Admission.status == "admitted"
    ).order_by(Admission.admission_date.desc()).all()

    out = []
    for a in admissions:
        p = db.query(Patient).filter(Patient.id == a.patient_id).first()
        out.append({
            "id": a.id, "patient_id": a.patient_id, "patient_name": p.name if p else "Unknown",
            "patient_uid": p.patient_uid if p else None, "ward": a.ward, "bed_number": a.bed_number,
            "status": a.status, "admission_date": a.admission_date.isoformat(), "days_admitted": _days_admitted(a),
        })
    return out


@router.get("/{admission_id}")
def get_admission(admission_id: int, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    patient = db.query(Patient).filter(Patient.id == a.patient_id).first()
    doctor = db.query(Doctor).filter(Doctor.id == a.admitting_doctor_id).first()

    meds = db.query(AdmissionMedicationOrder).filter(AdmissionMedicationOrder.admission_id == a.id).order_by(AdmissionMedicationOrder.created_at.desc()).all()
    med_out = []
    for m in meds:
        doses = db.query(AdmissionMedicationAdministration).filter(AdmissionMedicationAdministration.order_id == m.id).order_by(AdmissionMedicationAdministration.administered_at.desc()).all()
        med_out.append({
            "id": m.id, "medicine_name": m.medicine_name, "dosage": m.dosage, "route": m.route,
            "frequency_note": m.frequency_note, "is_active": m.is_active,
            "doses": [{"id": d.id, "administered_at": d.administered_at.isoformat(), "notes": d.notes} for d in doses],
        })

    charges = db.query(AdmissionCharge).filter(AdmissionCharge.admission_id == a.id).order_by(AdmissionCharge.charged_at.desc()).all()
    charges_out = [{"id": c.id, "charge_type": c.charge_type, "description": c.description, "amount": c.amount, "quantity": c.quantity, "charged_at": c.charged_at.isoformat()} for c in charges]

    tests = db.query(TestOrder).filter(TestOrder.admission_id == a.id).order_by(TestOrder.created_at.desc()).all()
    tests_out = [{"id": t.id, "test_name": t.test_name, "status": t.status, "price": t.price} for t in tests]

    charge_total = sum(c.amount * c.quantity for c in charges)
    room_total = _room_total(a)

    return {
        "id": a.id, "status": a.status, "ward": a.ward, "bed_number": a.bed_number,
        "diagnosis": a.diagnosis, "daily_room_charge": a.daily_room_charge,
        "admission_date": a.admission_date.isoformat(), "discharge_date": a.discharge_date.isoformat() if a.discharge_date else None,
        "days_admitted": _days_admitted(a), "discharge_summary": a.discharge_summary,
        "discharge_invoice_id": a.discharge_invoice_id,
        "patient": {"id": patient.id, "name": patient.name, "age": patient.age, "gender": patient.gender, "phone": patient.phone, "patient_uid": patient.patient_uid} if patient else None,
        "admitting_doctor_name": f"{doctor.title} {doctor.name}" if doctor else None,
        "medications": med_out,
        "charges": charges_out,
        "tests": tests_out,
        "bill": {
            "room_total": room_total, "charges_total": charge_total,
            "grand_total": room_total + charge_total,
        }
    }


# ---------- Medications (MAR) ----------

@router.post("/{admission_id}/medications")
def add_medication_order(admission_id: int, body: AddMedicationOrderIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    if a.status != "admitted":
        raise HTTPException(status_code=400, detail="Cannot add medications to a discharged admission")

    order = AdmissionMedicationOrder(
        admission_id=a.id, medicine_id=body.medicine_id, medicine_name=body.medicine_name,
        dosage=body.dosage, route=body.route, frequency_note=body.frequency_note,
        prescribed_by=current_doctor.id,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return {"id": order.id, "message": "Medication order added"}


@router.post("/{admission_id}/medications/{order_id}/administer")
def administer_dose(admission_id: int, order_id: int, body: AdministerDoseIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    order = db.query(AdmissionMedicationOrder).filter(AdmissionMedicationOrder.id == order_id, AdmissionMedicationOrder.admission_id == a.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Medication order not found")
    if not order.is_active:
        raise HTTPException(status_code=400, detail="This medication order has been stopped")

    admin_row = AdmissionMedicationAdministration(order_id=order.id, administered_by=current_doctor.id, administered_at=now_ist_naive(), notes=body.notes)
    db.add(admin_row)

    # Deduct real stock and auto-bill this dose — no manual billing step needed.
    unit_price = 0.0
    if order.medicine_id:
        medicine = db.query(HospitalMedicine).filter(HospitalMedicine.id == order.medicine_id).first()
        if medicine:
            deduct_stock_fefo(db, order.medicine_id, 1)
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
def stop_medication(admission_id: int, order_id: int, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    order = db.query(AdmissionMedicationOrder).filter(AdmissionMedicationOrder.id == order_id, AdmissionMedicationOrder.admission_id == a.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Medication order not found")
    order.is_active = False
    db.commit()
    return {"message": "Medication stopped"}


# ---------- Charges (manual: procedures, misc) ----------

@router.post("/{admission_id}/charges")
def add_charge(admission_id: int, body: AddChargeIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
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


# ---------- Tests during admission ----------

@router.post("/{admission_id}/tests")
def order_admission_test(admission_id: int, body: AddAdmissionTestIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    if a.status != "admitted":
        raise HTTPException(status_code=400, detail="Cannot order tests for a discharged admission")

    test = TestOrder(
        admission_id=a.id, patient_id=a.patient_id, hospital_id=a.hospital_id,
        test_id=body.test_id, test_name=body.test_name, price=body.price,
        included=False, status="paid",  # billed at discharge, so it can go straight to the lab queue
        paid_at=now_ist_naive(), queued_at=now_ist_naive(),
    )
    db.add(test)
    db.add(AdmissionCharge(
        admission_id=a.id, charge_type="test", description=body.test_name,
        amount=body.price, quantity=1, added_by=current_doctor.id, charged_at=now_ist_naive(),
    ))
    db.commit()
    return {"message": "Test ordered"}


# ---------- Discharge ----------

@router.post("/{admission_id}/discharge")
def discharge_patient(admission_id: int, body: DischargeIn, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    if a.status != "admitted":
        raise HTTPException(status_code=400, detail="Already discharged")

    a.status = "discharged"
    a.discharge_date = now_ist_naive()
    a.discharge_summary = body.discharge_summary
    db.commit()

    patient = db.query(Patient).filter(Patient.id == a.patient_id).first()
    hospital = db.query(Hospital).filter(Hospital.id == a.hospital_id).first()
    charges = db.query(AdmissionCharge).filter(AdmissionCharge.admission_id == a.id).all()

    items = [{"type": "room", "name": f"Room charges — {a.ward}, Bed {a.bed_number} ({_days_admitted(a)} day(s))",
              "qty": _days_admitted(a), "unit_price": a.daily_room_charge, "line_total": _room_total(a)}]
    for c in charges:
        items.append({"type": c.charge_type, "name": c.description, "qty": c.quantity, "unit_price": c.amount, "line_total": c.amount * c.quantity})

    grand_total = sum(i["line_total"] for i in items)

    invoice = Invoice(
        checkin_id=None, admission_id=a.id, patient_id=a.patient_id, hospital_id=a.hospital_id,
        items_json=json.dumps(items), grand_total=grand_total,
        generated_by=current_doctor.id, generated_from="admission_discharge",
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)

    admitting_doctor = db.query(Doctor).filter(Doctor.id == a.admitting_doctor_id).first()
    pdf_path = generate_invoice_pdf(invoice.id, hospital, items, grand_total, patient, admitting_doctor)
    invoice.pdf_path = pdf_path
    a.discharge_invoice_id = invoice.id
    db.commit()

    return {"message": "Patient discharged", "invoice_id": invoice.id, "grand_total": grand_total}


@router.get("/{admission_id}/invoice/pdf")
def download_discharge_invoice(admission_id: int, current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    a = _get_admission_or_404(db, admission_id, current_doctor.hospital_id)
    if not a.discharge_invoice_id:
        raise HTTPException(status_code=404, detail="No discharge invoice yet")
    invoice = db.query(Invoice).filter(Invoice.id == a.discharge_invoice_id).first()
    if not invoice or not invoice.pdf_path:
        raise HTTPException(status_code=404, detail="Invoice PDF not found")
    return FileResponse(invoice.pdf_path, media_type="application/pdf", filename=f"discharge_invoice_{admission_id}.pdf")