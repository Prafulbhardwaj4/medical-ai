from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List
from app.database import get_db
from app.models.consultation import Consultation
from app.models.patient import Patient
from app.models.doctor import Doctor, UserRole
from app.schemas.consultation import ConsultationOut, ConsultationHistoryItem, ConsultationStructured, MedicineItem, StructureRequest
from app.utils.auth import get_current_doctor, now_ist, decode_access_token, is_token_blacklisted
from app.utils.audit import log_action
from app.services.whisper import transcribe_audio
from app.services.groq_service import structure_transcript
from app.services.pdf_service import generate_prescription_pdf
from app.services.sms_service import send_sms
from app.services.sarvam_stream import stream_transcribe
from app.models.doctor import Doctor as DoctorModel
from app.models.checkin import Checkin
from app.models.hospital import Hospital
from app.models.test_catalog import TestCatalogItem
from app.models.test_order import TestOrder
from app.models.medicine_order import MedicineOrder
from app.models.hospital_medicine import HospitalMedicine
from app.utils.inventory import deduct_stock_fefo, calculate_prescribed_quantity
from app.utils.notify import sync_stock_notifications
from app.schemas.consultation import ConfirmPrescriptionPayload
from app.config import settings
from sqlalchemy import exists, func
import json
import asyncio
from datetime import datetime, date
import pytz
from fastapi.responses import FileResponse
import os
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/consultations", tags=["consultations"])


@router.get("/today")
def today_consultations(current_doctor: Doctor = Depends(get_current_doctor), db: Session = Depends(get_db)):
    ist = pytz.timezone("Asia/Kolkata")
    now_ist = datetime.now(ist)
    start_of_day = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    count = db.query(Consultation).filter(
        Consultation.doctor_id == current_doctor.id,
        Consultation.created_at >= start_of_day,
        Consultation.is_voided == False
    ).count()
    return {"count": count}

@router.get("/analytics")
def get_analytics(
    current_doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db)
):
    from sqlalchemy import func
    import json

    # Scope by hospital for admin/super_admin, by doctor for doctor/sub_admin
    if current_doctor.role.value in ["admin", "super_admin"]:
        hospital_doctor_ids = [
            d.id for d in db.query(Doctor).filter(
                Doctor.hospital_id == current_doctor.hospital_id
            ).all()
        ]
        base = db.query(Consultation).filter(
            Consultation.doctor_id.in_(hospital_doctor_ids),
            Consultation.token_number != None,
            Consultation.is_voided == False
        )
        patients = db.query(Patient).filter(
            Patient.hospital_id == current_doctor.hospital_id
        ).all()
        total_patients = len(patients)
    else:
        base = db.query(Consultation).filter(
            Consultation.doctor_id == current_doctor.id,
            Consultation.token_number != None,
            Consultation.is_voided == False
        )
        patients = db.query(Patient).filter(
            Patient.hospital_id == current_doctor.hospital_id
        ).all()
        total_patients = len(patients)

    total_consultations = base.count()

    # Load only fields needed for JSON parsing — no full ORM objects
    all_consultations = base.with_entities(
        Consultation.created_at,
        Consultation.diagnosis,
        Consultation.medicines,
        Consultation.tests
    ).order_by(Consultation.created_at).all()

    daily_counts = {}
    for c in all_consultations:
        day = c.created_at.strftime("%d %b")
        daily_counts[day] = daily_counts.get(day, 0) + 1

    # Age + gender distribution via DB aggregation
    age_groups = {"0-12": 0, "13-25": 0, "26-40": 0, "41-60": 0, "60+": 0}
    gender_counts = {}
    for p in patients:
        if p.age <= 12: age_groups["0-12"] += 1
        elif p.age <= 25: age_groups["13-25"] += 1
        elif p.age <= 40: age_groups["26-40"] += 1
        elif p.age <= 60: age_groups["41-60"] += 1
        else: age_groups["60+"] += 1
        g = p.gender.capitalize()
        gender_counts[g] = gender_counts.get(g, 0) + 1


    # Top diagnoses
    diagnosis_counts = {}
    for c in all_consultations:
        if c.diagnosis:
            d = c.diagnosis.strip().lower().capitalize()
            diagnosis_counts[d] = diagnosis_counts.get(d, 0) + 1
    top_diagnoses = sorted(diagnosis_counts.items(), key=lambda x: x[1], reverse=True)[:8]

    # Top medicines + OTC vs Rx
    medicine_counts = {}
    otc_count = 0
    rx_count = 0
    for c in all_consultations:
        meds = json.loads(c.medicines or "[]")
        for m in meds:
            name = m.get("name", "").strip().capitalize()
            if name:
                medicine_counts[name] = medicine_counts.get(name, 0) + 1
            if m.get("schedule") == "otc":
                otc_count += 1
            else:
                rx_count += 1
    top_medicines = sorted(medicine_counts.items(), key=lambda x: x[1], reverse=True)[:8]

    # Tests ordered
    test_counts = {}
    for c in all_consultations:
        tests = json.loads(c.tests or "[]")
        for t in tests:
            t = t.strip().capitalize()
            if t:
                test_counts[t] = test_counts.get(t, 0) + 1
    top_tests = sorted(test_counts.items(), key=lambda x: x[1], reverse=True)[:6]

    return {
        "summary": {
            "total_consultations": total_consultations,
            "total_patients": total_patients,
            "otc_medicines": otc_count,
            "rx_medicines": rx_count
        },
        "daily_consultations": daily_counts,
        "age_groups": age_groups,
        "gender_distribution": gender_counts,
        "top_diagnoses": [{"name": k, "count": v} for k, v in top_diagnoses],
        "top_medicines": [{"name": k, "count": v} for k, v in top_medicines],
        "top_tests": [{"name": k, "count": v} for k, v in top_tests]
    }

@router.post("/transcribe/{patient_id}")
@limiter.limit("10/minute")
async def transcribe(
    request: Request,
    patient_id: int,
    audio: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    patient = db.query(Patient).filter(
        Patient.id == patient_id,
        Patient.hospital_id == current_doctor.hospital_id
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    audio_bytes = await audio.read()

    ALLOWED_AUDIO_TYPES = [
        "audio/webm",
        "audio/webm;codecs=opus",
        "audio/ogg",
        "audio/ogg;codecs=opus",
        "audio/m4a",
        "audio/mpeg",
        "audio/wav",
        "audio/mp4"
    ]
    MAX_AUDIO_SIZE = 25 * 1024 * 1024  # 25MB

    if audio.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid file type: {audio.content_type}. Allowed: webm, m4a, mp3, wav")

    if len(audio_bytes) > MAX_AUDIO_SIZE:
        raise HTTPException(status_code=400, detail="Audio file too large. Max 25MB allowed.")

    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    try:
        transcript = await transcribe_audio(audio_bytes, audio.filename or "recording.webm")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Whisper transcription failed: {str(e)}")

    # Reuse existing unconfirmed draft if one exists, else create new
    consultation = db.query(Consultation).filter(
        Consultation.patient_id == patient_id,
        Consultation.doctor_id == current_doctor.id,
        Consultation.token_number == None
    ).first()

    if consultation:
        consultation.raw_transcript = transcript
    else:
        consultation = Consultation(
            patient_id=patient_id,
            doctor_id=current_doctor.id,
            raw_transcript=transcript
        )
        db.add(consultation)

    db.commit()
    db.refresh(consultation)

    return {
        "consultation_id": consultation.id,
        "transcript": transcript
    }


@router.websocket("/ws/transcribe/{patient_id}")
async def websocket_transcribe(
    websocket: WebSocket,
    patient_id: int,
    token: str,
    db: Session = Depends(get_db)
):
    payload = decode_access_token(token)
    if not payload:
        await websocket.close(code=4001)
        return

    if is_token_blacklisted(token, db):
        await websocket.close(code=4001)
        return

    doctor = db.query(DoctorModel).filter(
        DoctorModel.id == int(payload.get("sub"))
    ).first()
    if not doctor or not doctor.is_active:
        await websocket.close(code=4001)
        return

    patient = db.query(Patient).filter(
        Patient.id == patient_id,
        Patient.hospital_id == doctor.hospital_id
    ).first()
    if not patient:
        await websocket.close(code=4003)
        return

    await websocket.accept()

    audio_queue = asyncio.Queue()
    transcript_queue = asyncio.Queue()

    stream_task = asyncio.create_task(
        stream_transcribe(audio_queue, transcript_queue)
    )

    full_transcript = ""

    async def receive_audio():
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    await audio_queue.put(message["bytes"])
                elif message.get("text") is not None:
                    try:
                        payload = json.loads(message["text"])
                    except Exception:
                        payload = {}
                    if payload.get("type") == "stop":
                        break
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            await audio_queue.put(None)

    async def send_transcript():
        nonlocal full_transcript
        while True:
            try:
                msg = await asyncio.wait_for(transcript_queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                break

            if msg["type"] == "transcript":
                full_transcript += " " + msg["text"]
                try:
                    await websocket.send_json({
                        "type": "transcript",
                        "text": msg["text"],
                        "full": full_transcript.strip()
                    })
                except Exception:
                    break

            elif msg["type"] == "end":
                break

            elif msg["type"] == "error":
                try:
                    await websocket.send_json({
                        "type": "error",
                        "message": msg["message"]
                    })
                except Exception:
                    pass
                break

        # Save consultation
        try:
            consultation = db.query(Consultation).filter(
                Consultation.patient_id == patient_id,
                Consultation.doctor_id == doctor.id,
                Consultation.token_number == None
            ).first()

            transcript_text = full_transcript.strip()

            if consultation:
                consultation.raw_transcript = transcript_text
            else:
                consultation = Consultation(
                    patient_id=patient_id,
                    doctor_id=doctor.id,
                    raw_transcript=transcript_text
                )
                db.add(consultation)
            db.commit()
            db.refresh(consultation)

            try:
                await websocket.send_json({
                    "type": "done",
                    "consultation_id": consultation.id,
                    "transcript": transcript_text
                })
            except Exception:
                pass
        except Exception as e:
            try:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Failed to save: {str(e)}"
                })
            except Exception:
                pass

    try:
        await asyncio.gather(receive_audio(), send_transcript())
    except Exception:
        pass
    finally:
        stream_task.cancel()
        try:
            await websocket.close()
        except Exception:
            pass


@router.get("/test-catalog")
def get_test_catalog(
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    items = db.query(TestCatalogItem).filter(
        TestCatalogItem.hospital_id == current_doctor.hospital_id,
        TestCatalogItem.is_active == True
    ).all()
    return [{"id": i.id, "name": i.name, "fee": i.fee} for i in items]

@router.get("/history/{patient_id}", response_model=List[ConsultationHistoryItem])
def get_history(
    patient_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    patient = db.query(Patient).filter(
        Patient.id == patient_id,
        Patient.hospital_id == current_doctor.hospital_id
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    consultations = (
        db.query(Consultation, DoctorModel)
        .outerjoin(DoctorModel, Consultation.doctor_id == DoctorModel.id)
        .filter(
            Consultation.patient_id == patient_id,
            Consultation.token_number != None,
            Consultation.is_voided == False
        )
        .order_by(desc(Consultation.created_at))
        .all()
    )

    result = []
    for c, doctor in consultations:
        item = ConsultationHistoryItem(
            id=c.id,
            token_number=c.token_number,
            created_at=c.created_at,
            chief_complaint=c.chief_complaint,
            diagnosis=c.diagnosis,
            medicines=c.medicines,
            tests=c.tests,
            advice=c.advice,
            followup=c.followup,
            whatsapp_status=c.whatsapp_status,
            vitals=c.vitals,
            ordered_tests=c.ordered_tests,
            doctor_name=f"{doctor.title} {doctor.name}" if doctor else "—",
            doctor_specialization=doctor.specialization if doctor else None
        )
        result.append(item)
    return result

@router.get("/prescriptions/{token_number}.pdf")
def get_prescription_pdf(
    token_number: str,
    current_doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db)
):
    consultation = db.query(Consultation).join(
        Patient, Consultation.patient_id == Patient.id
    ).filter(
        Consultation.token_number == token_number,
        Consultation.is_voided == False,
        Patient.hospital_id == current_doctor.hospital_id
    ).first()

    if not consultation:
        raise HTTPException(status_code=404, detail="Prescription not found")

    safe_token = os.path.basename(token_number)
    pdf_path = os.path.join("prescriptions", f"{safe_token}.pdf")
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF file not found")

    return FileResponse(pdf_path, media_type="application/pdf", filename=f"{safe_token}.pdf")


@router.get("/verify/{token_number}")
@limiter.limit("10/minute")
def verify_prescription(request: Request, token_number: str, hash: str, db: Session = Depends(get_db)):
    consultation = db.query(Consultation).filter(
        Consultation.token_number == token_number
    ).first()

    if not consultation:
        return {"valid": False, "reason": "Token not found"}

    if consultation.verify_hash != hash:
        return {"valid": False, "reason": "Verification code mismatch — possible tampering"}

    patient = db.query(Patient).filter(Patient.id == consultation.patient_id).first()
    doctor = db.query(DoctorModel).filter(DoctorModel.id == consultation.doctor_id).first()

    medicines = json.loads(consultation.medicines or "[]")

    name_parts = patient.name.split()
    masked_name = name_parts[0]
    if len(name_parts) > 1:
        masked_name += f" {name_parts[1][0]}."

    return {
        "valid": True,
        "token_number": consultation.token_number,
        "doctor_name": f"{doctor.title} {doctor.name}",
        "clinic_name": doctor.clinic_name,
        "specialization": doctor.specialization,
        "patient_name": masked_name,
        "date": consultation.created_at.isoformat(),
        "medicines": medicines,
        "is_dispensed": consultation.is_dispensed,
        "dispensed_at": consultation.dispensed_at.isoformat() if consultation.dispensed_at else None
    }


@router.post("/verify/{token_number}/dispense")
@limiter.limit("10/minute")
def mark_dispensed(
    request: Request,
    token_number: str,
    hash: str,
    db: Session = Depends(get_db)
):
    consultation = db.query(Consultation).filter(
        Consultation.token_number == token_number,
        Consultation.verify_hash == hash,
        Consultation.is_voided == False
    ).first()

    if not consultation:
        raise HTTPException(status_code=404, detail="Invalid token or verification code")

    if consultation.is_dispensed:
        raise HTTPException(status_code=400, detail="Already marked as dispensed")

    consultation.is_dispensed = True
    consultation.dispensed_at = now_ist()

    paid_medicine_orders = db.query(MedicineOrder).filter(
        MedicineOrder.consultation_id == consultation.id,
        MedicineOrder.status == "paid"
    ).all()
    for mo in paid_medicine_orders:
        mo.status = "dispensed"
        mo.dispensed_at = now_ist()

        if mo.catalog_medicine_id and mo.quantity:
            result = deduct_stock_fefo(db, mo.catalog_medicine_id, mo.quantity)
            db.commit()
            sync_stock_notifications(db, mo.hospital_id)
            log_action(
                db, None,
                action="medicine_dispensed",
                target_type="hospital_medicine",
                target_id=mo.catalog_medicine_id,
                target_label=f"{result['medicine_name']} -{mo.quantity}" + (f" (shortfall {result['shortfall']})" if result["shortfall"] > 0 else ""),
                hospital_id=mo.hospital_id
            )
    db.commit()

    log_action(
        db, None,
        action="prescription_dispensed",
        target_type="consultation",
        target_id=consultation.id,
        target_label=consultation.token_number,
        hospital_id=None
    )

    return {"message": "Marked as dispensed", "dispensed_at": consultation.dispensed_at.isoformat()}


@router.post("/structure/{consultation_id}")
@limiter.limit("10/minute")
async def structure(
    request: Request,
    consultation_id: int,
    payload: StructureRequest = StructureRequest(),
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    consultation = db.query(Consultation).filter(
        Consultation.id == consultation_id,
        Consultation.doctor_id == current_doctor.id
    ).first()
    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found")

    if payload.transcript and payload.transcript.strip():
        consultation.raw_transcript = payload.transcript.strip()
        db.commit()

    if not consultation.raw_transcript:
        raise HTTPException(status_code=400, detail="No transcript found for this consultation")

    previous = (
        db.query(Consultation)
        .filter(
            Consultation.patient_id == consultation.patient_id,
            Consultation.id != consultation_id,
            Consultation.diagnosis != None
        )
        .order_by(desc(Consultation.created_at))
        .limit(3)
        .all()
    )

    history_text = ""
    if previous:
        lines = []
        for p in previous:
            lines.append(f"- Visit {p.created_at.strftime('%d %b %Y')}: diagnosis={p.diagnosis}, medicines={p.medicines}")
        history_text = "\n".join(lines)

    try:
        structured = await structure_transcript(consultation.raw_transcript, history_text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI structuring failed: {str(e)}")

    consultation.chief_complaint = structured.get("chief_complaint", "")
    consultation.diagnosis = structured.get("diagnosis", "")
    consultation.medicines = json.dumps(structured.get("medicines", []))
    consultation.tests = json.dumps(structured.get("tests", []))
    consultation.advice = structured.get("advice", "")
    consultation.followup = structured.get("followup", "")
    consultation.has_pending_tests = len(structured.get("tests", [])) > 0
    consultation.vitals = json.dumps(structured.get("vitals", {}))

    db.commit()
    db.refresh(consultation)

    return {
        "consultation_id": consultation.id,
        "structured": structured
    }


@router.post("/confirm/{consultation_id}")
@limiter.limit("10/minute")
def confirm_prescription(
    request: Request,
    consultation_id: int,
    payload: ConfirmPrescriptionPayload = ConfirmPrescriptionPayload(),
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    consultation = db.query(Consultation).filter(
        Consultation.id == consultation_id,
        Consultation.doctor_id == current_doctor.id
    ).first()
    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found")
    if not consultation.medicines:
        raise HTTPException(status_code=400, detail="Consultation not structured yet. Run /structure first.")
    if consultation.token_number:
        raise HTTPException(status_code=400, detail="Prescription already confirmed.")

    patient = db.query(Patient).filter(Patient.id == consultation.patient_id).first()

    import hashlib

    todays_checkin = db.query(Checkin).filter(
        Checkin.patient_id == consultation.patient_id,
        Checkin.visit_date == date.today()
    ).order_by(desc(Checkin.created_at)).first()

    if todays_checkin:
        token_number = todays_checkin.token_number
        clash = db.query(Consultation).filter(
            Consultation.token_number == token_number,
            Consultation.id != consultation.id
        ).first()
        if clash:
            suffix = 2
            while db.query(Consultation).filter(Consultation.token_number == f"{token_number}-{suffix}").first():
                suffix += 1
            token_number = f"{token_number}-{suffix}"
    else:
        # Fallback: no check-in exists yet (shouldn't normally happen), create one now
        hospital = db.query(Hospital).filter(Hospital.id == current_doctor.hospital_id).first()
        hospital_code = hospital.hospital_code if hospital else "GEN"
        prefix = hospital_code.replace("-", "")[:4].upper()
        date_part = date.today().strftime("%d%m%y")
        while True:
            count = db.query(Checkin).filter(
                Checkin.hospital_id == current_doctor.hospital_id,
                Checkin.visit_date == date.today()
            ).count() + 1
            token_number = f"{prefix}-{date_part}-{count:03d}"
            if not db.query(Checkin).filter(Checkin.token_number == token_number).first():
                break

        fallback_checkin = Checkin(
            hospital_id=current_doctor.hospital_id,
            patient_id=consultation.patient_id,
            token_number=token_number,
            issue_category="General OPD",
            doctor_id=current_doctor.id,
            created_by=current_doctor.id,
            visit_date=date.today()
        )
        db.add(fallback_checkin)

    if todays_checkin and todays_checkin.vitals_data:
        try:
            nurse_vitals = json.loads(todays_checkin.vitals_data)
            label_to_key = {
                "Blood Pressure": "bp",
                "Pulse": "pulse",
                "Temperature": "temperature",
                "Weight": "weight",
                "SpO2": "spo2",
            }
            normalized_nurse_vitals = {}
            for k, v in nurse_vitals.items():
                normalized_nurse_vitals[label_to_key.get(k, k)] = v
            existing_vitals = json.loads(consultation.vitals or "{}")
            consultation.vitals = json.dumps({**normalized_nurse_vitals, **existing_vitals})
        except Exception:
            pass

    if payload.recommended_test_ids:
        test_items = db.query(TestCatalogItem).filter(
            TestCatalogItem.id.in_(payload.recommended_test_ids),
            TestCatalogItem.hospital_id == current_doctor.hospital_id
        ).all()
        consultation.recommended_test_ids = json.dumps([t.id for t in test_items])
        consultation.ordered_tests = json.dumps([
            {"test_id": t.id, "test_name": t.name, "price": t.fee, "status": "payment_pending"}
            for t in test_items
        ])
        total_test_fee = sum(t.fee for t in test_items)
        if total_test_fee > 0:
            billing_target = todays_checkin if todays_checkin else fallback_checkin
            billing_target.test_fee = total_test_fee
            if billing_target.is_paid:
                billing_target.is_paid = False

        for t in test_items:
            db.add(TestOrder(
                consultation_id=consultation.id,
                patient_id=consultation.patient_id,
                hospital_id=current_doctor.hospital_id,
                test_id=t.id,
                test_name=t.name,
                price=t.fee,
                status="payment_pending"
            ))

    try:
        prescribed_medicines = json.loads(consultation.medicines or "[]")
    except Exception:
        prescribed_medicines = []

    if prescribed_medicines:
        catalog_medicines = db.query(HospitalMedicine).filter(
            HospitalMedicine.hospital_id == current_doctor.hospital_id,
            HospitalMedicine.is_active == True
        ).all()

        def match_catalog(name, brand):
            search_terms = [t for t in [(name or "").strip().lower(), (brand or "").strip().lower()] if t]
            for cm in catalog_medicines:
                cm_generic = (cm.generic_name or "").strip().lower()
                cm_brands = [b.strip().lower() for b in (cm.brand_names or "").split(",") if b.strip()]
                for term in search_terms:
                    if term and (term == cm_generic or term in cm_brands or cm_generic in term):
                        return cm
            return None

        for med in prescribed_medicines:
            name = med.get("name", "")
            brand = med.get("brand_name", "")
            matched = match_catalog(name, brand)

            quantity = calculate_prescribed_quantity(
                matched, med.get("times_per_day"), med.get("duration_days")
            )

            db.add(MedicineOrder(
                consultation_id=consultation.id,
                patient_id=consultation.patient_id,
                hospital_id=current_doctor.hospital_id,
                catalog_medicine_id=matched.id if matched else None,
                medicine_name=name,
                brand_name=brand,
                dosage=med.get("dosage", ""),
                frequency=med.get("frequency", ""),
                duration=med.get("duration", ""),
                unit_price=matched.price if matched else None,
                quantity=quantity,
                included=True,
                status="advised"
            ))

    consultation.token_number = token_number

    hash_input = f"{token_number}-{current_doctor.id}-{consultation.id}-{settings.SECRET_KEY}"
    verify_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16].upper()
    consultation.verify_hash = verify_hash

    try:
        pdf_path = generate_prescription_pdf(current_doctor, patient, consultation, token_number, verify_hash)
        consultation.pdf_path = pdf_path
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)}")

    db.commit()
    db.refresh(consultation)

    log_action(
        db, current_doctor,
        action="prescription_confirmed",
        target_type="consultation",
        target_id=consultation.id,
        target_label=token_number,
        details=f"Patient: {patient.name} ({patient.patient_uid})"
    )

    return {
        "consultation_id": consultation.id,
        "token_number": token_number,
        "verify_hash": verify_hash,
        "pdf_path": pdf_path,
        "message": "Prescription confirmed and PDF generated."
    }


@router.patch("/update/{consultation_id}")
def update_consultation(
    consultation_id: int,
    payload: ConsultationStructured,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    consultation = db.query(Consultation).filter(
        Consultation.id == consultation_id,
        Consultation.doctor_id == current_doctor.id
    ).first()
    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found")
    if consultation.token_number:
        raise HTTPException(status_code=400, detail="Cannot edit a confirmed prescription.")

    consultation.chief_complaint = payload.chief_complaint
    consultation.diagnosis = payload.diagnosis
    consultation.medicines = json.dumps([m.dict() for m in payload.medicines])
    consultation.tests = json.dumps(payload.tests)
    consultation.advice = payload.advice
    consultation.followup = payload.followup
    consultation.has_pending_tests = len(payload.tests) > 0
    consultation.vitals = json.dumps(payload.vitals.dict() if payload.vitals else {})

    db.commit()
    db.refresh(consultation)
    return {"message": "Consultation updated successfully"}


@router.post("/void/{consultation_id}")
def void_consultation(
    consultation_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    consultation = db.query(Consultation).filter(
        Consultation.id == consultation_id,
        Consultation.doctor_id == current_doctor.id
    ).first()
    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found")

    consultation.is_voided = True
    db.commit()

    log_action(
        db, current_doctor,
        action="consultation_voided",
        target_type="consultation",
        target_id=consultation.id,
        target_label=consultation.token_number or f"Draft #{consultation.id}",
        details=f"Patient ID: {consultation.patient_id}"
    )

    return {"message": "Consultation voided"}


@router.post("/send-sms/{consultation_id}")
@limiter.limit("5/minute")
def send_prescription_sms(
    request: Request,
    consultation_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    consultation = db.query(Consultation).filter(
        Consultation.id == consultation_id,
        Consultation.doctor_id == current_doctor.id
    ).first()
    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found")
    if not consultation.token_number:
        raise HTTPException(status_code=400, detail="Prescription not confirmed yet.")

    patient = db.query(Patient).filter(Patient.id == consultation.patient_id).first()

    pdf_filename = f"{consultation.token_number}.pdf"
    pdf_url = f"{settings.BASE_URL}/prescriptions/{pdf_filename}"

    result = send_sms(
        to_phone=patient.phone,
        doctor_name=f"{current_doctor.title} {current_doctor.name}",
        token_number=consultation.token_number,
        pdf_url=pdf_url
    )

    consultation.whatsapp_status = result["status"]
    db.commit()

    if result["status"] == "failed":
        raise HTTPException(status_code=502, detail=f"SMS delivery failed: {result.get('error')}")

    return {
        "consultation_id": consultation.id,
        "token_number": consultation.token_number,
        "sms_status": result["status"],
        "pdf_url": pdf_url,
        "sent_to": patient.phone
    }

@router.get("/admin-dashboard")
def admin_dashboard(
    current_doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db)
):
    import json
    from datetime import datetime, timedelta
    from sqlalchemy import func, case
    from app.models.hospital import Hospital

    if current_doctor.role.value not in ["admin", "sub_admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    hospital_doctors = db.query(DoctorModel).filter(
        DoctorModel.hospital_id == current_doctor.hospital_id,
        DoctorModel.role.in_(["doctor", "sub_admin"])
    ).all()
    doctor_ids = [d.id for d in hospital_doctors]
    doctor_map = {d.id: d for d in hospital_doctors}

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # DB-level counts instead of loading all into memory
    total_consults = db.query(Consultation).filter(
        Consultation.doctor_id.in_(doctor_ids),
        Consultation.token_number != None,
        Consultation.is_voided == False
    ).count()

    today_count = db.query(Consultation).filter(
        Consultation.doctor_id.in_(doctor_ids),
        Consultation.token_number != None,
        Consultation.is_voided == False,
        Consultation.created_at >= today_start
    ).count()

    week_count = db.query(Consultation).filter(
        Consultation.doctor_id.in_(doctor_ids),
        Consultation.token_number != None,
        Consultation.is_voided == False,
        Consultation.created_at >= week_start
    ).count()

    month_count = db.query(Consultation).filter(
        Consultation.doctor_id.in_(doctor_ids),
        Consultation.token_number != None,
        Consultation.is_voided == False,
        Consultation.created_at >= month_start
    ).count()

    voided_consults = db.query(Consultation).filter(
        Consultation.doctor_id.in_(doctor_ids),
        Consultation.is_voided == True
    ).count()

    total_attempted = total_consults + voided_consults

    # Load only what's needed for JSON parsing (medicines/tests/diagnosis)
    all_consults = db.query(Consultation).filter(
        Consultation.doctor_id.in_(doctor_ids),
        Consultation.token_number != None,
        Consultation.is_voided == False
    ).with_entities(
        Consultation.id,
        Consultation.patient_id,
        Consultation.doctor_id,
        Consultation.created_at,
        Consultation.token_number,
        Consultation.diagnosis,
        Consultation.medicines,
        Consultation.tests
    ).all()

    today_consults = [c for c in all_consults if c.created_at >= today_start]
    week_consults = [c for c in all_consults if c.created_at >= week_start]
    month_consults = [c for c in all_consults if c.created_at >= month_start]

    # All patients
    all_patients = db.query(Patient).filter(
        Patient.hospital_id == current_doctor.hospital_id
    ).all()
    patient_map = {p.id: p for p in all_patients}
    new_patients_month = [p for p in all_patients if p.created_at >= month_start]

    # New vs returning patients
    # A patient is "returning" if they have more than 1 consultation
    patient_consult_count = {}
    for c in all_consults:
        patient_consult_count[c.patient_id] = patient_consult_count.get(c.patient_id, 0) + 1
    new_patient_visits = sum(1 for count in patient_consult_count.values() if count == 1)
    returning_patient_visits = sum(1 for count in patient_consult_count.values() if count > 1)

    # Check-ins, for last-visit fallback (covers patients who checked in but haven't been consulted yet)
    all_checkins = db.query(Checkin).filter(
        Checkin.hospital_id == current_doctor.hospital_id
    ).all()
    patient_checkins = {}
    for chk in all_checkins:
        existing = patient_checkins.get(chk.patient_id)
        if not existing or chk.created_at > existing.created_at:
            patient_checkins[chk.patient_id] = chk

    # Check-in counts per patient (a check-in counts as a visit even before consultation)
    patient_checkin_count = {}
    for chk in all_checkins:
        patient_checkin_count[chk.patient_id] = patient_checkin_count.get(chk.patient_id, 0) + 1

    # Build a map of patient_id -> most recent checkin's doctor_id
    from app.models.checkin import Checkin as CheckinModel
    latest_checkin_doctor = {}
    recent_checkins = db.query(CheckinModel).filter(
        CheckinModel.hospital_id == current_doctor.hospital_id
    ).order_by(CheckinModel.created_at.desc()).all()
    for chk in recent_checkins:
        if chk.patient_id not in latest_checkin_doctor:
            latest_checkin_doctor[chk.patient_id] = chk.doctor_id

    # Patients list
    patients_list = []
    for p in sorted(all_patients, key=lambda x: x.created_at, reverse=True):
        last_checkin = patient_checkins.get(p.id)
        doctor = doctor_map.get(last_checkin.doctor_id) if last_checkin else None
        consult_count = max(patient_consult_count.get(p.id, 0), patient_checkin_count.get(p.id, 0))
        last_consult = max(
            [c for c in all_consults if c.patient_id == p.id],
            key=lambda c: c.created_at,
            default=None
        )

        candidates = []
        if last_consult:
            candidates.append(last_consult.created_at)
        if last_checkin:
            candidates.append(last_checkin.created_at)
        last_visit_dt = max(candidates) if candidates else None

        patients_list.append({
            "patient_uid": p.patient_uid,
            "name": p.name,
            "age": p.age,
            "gender": p.gender,
            "blood_group": p.blood_group or "—",
            "phone": p.phone,
            "doctor": f"{doctor.title} {doctor.name}" if doctor else "—",
            "total_visits": consult_count,
            "last_visit": last_visit_dt.strftime("%d %b %Y") if last_visit_dt else "—",
            "registered": p.created_at.strftime("%d %b %Y")
        })

    # Per doctor stats
    doctor_stats = []
    for d in hospital_doctors:
        d_consults = [c for c in all_consults if c.doctor_id == d.id]
        d_today = [c for c in today_consults if c.doctor_id == d.id]
        d_week = [c for c in week_consults if c.doctor_id == d.id]
        last_consult = max(d_consults, key=lambda c: c.created_at) if d_consults else None
        doctor_stats.append({
            "id": d.id,
            "name": f"{d.title} {d.name}",
            "specialization": d.specialization,
            "is_active": d.is_active,
            "total_consultations": len(d_consults),
            "today_consultations": len(d_today),
            "week_consultations": len(d_week),
            "last_active": last_consult.created_at.isoformat() if last_consult else None
        })

    # Recent consultations
    recent_consults = sorted(all_consults, key=lambda c: c.created_at, reverse=True)[:20]
    recent_list = []
    for c in recent_consults:
        patient = patient_map.get(c.patient_id)
        doctor = doctor_map.get(c.doctor_id)
        recent_list.append({
            "token": c.token_number,
            "patient_name": patient.name if patient else "—",
            "patient_uid": patient.patient_uid if patient else "—",
            "doctor_name": f"{doctor.title} {doctor.name}" if doctor else "—",
            "diagnosis": c.diagnosis or "—",
            "date": c.created_at.strftime("%d %b %Y %I:%M %p")
        })

    # Medicine stats
    medicine_counts = {}
    medicine_diagnosis = {}
    otc_count = 0
    rx_count = 0
    for c in all_consults:
        meds = json.loads(c.medicines or "[]")
        for m in meds:
            name = m.get("name", "").strip().capitalize()
            if name:
                medicine_counts[name] = medicine_counts.get(name, 0) + 1
                if c.diagnosis:
                    diag = c.diagnosis.strip().capitalize()
                    if name not in medicine_diagnosis:
                        medicine_diagnosis[name] = {}
                    medicine_diagnosis[name][diag] = medicine_diagnosis[name].get(diag, 0) + 1
            if m.get("schedule") == "otc":
                otc_count += 1
            else:
                rx_count += 1

    top_medicines_detailed = []
    for name, count in sorted(medicine_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
        diag_map = medicine_diagnosis.get(name, {})
        top_diag = max(diag_map.items(), key=lambda x: x[1])[0] if diag_map else "—"
        top_medicines_detailed.append({
            "name": name,
            "count": count,
            "top_diagnosis": top_diag
        })

    # Test stats
    test_counts = {}
    for c in all_consults:
        tests = json.loads(c.tests or "[]")
        for t in tests:
            t = t.strip().capitalize()
            if t:
                test_counts[t] = test_counts.get(t, 0) + 1
    top_tests = sorted(test_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Diagnosis stats
    diagnosis_counts = {}
    for c in all_consults:
        if c.diagnosis:
            d = c.diagnosis.strip().capitalize()
            diagnosis_counts[d] = diagnosis_counts.get(d, 0) + 1
    top_diagnoses = sorted(diagnosis_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Demographics
    age_groups = {"0-12": 0, "13-25": 0, "26-40": 0, "41-60": 0, "60+": 0}
    gender_counts = {}
    blood_groups = {}
    age_diagnosis = {}
    gender_diagnosis = {}

    for p in all_patients:
        if p.age <= 12: ag = "0-12"
        elif p.age <= 25: ag = "13-25"
        elif p.age <= 40: ag = "26-40"
        elif p.age <= 60: ag = "41-60"
        else: ag = "60+"
        age_groups[ag] += 1
        g = p.gender.capitalize()
        gender_counts[g] = gender_counts.get(g, 0) + 1
        if p.blood_group:
            bg = p.blood_group.strip().upper()
            blood_groups[bg] = blood_groups.get(bg, 0) + 1

    for c in all_consults:
        patient = patient_map.get(c.patient_id)
        if not patient or not c.diagnosis:
            continue
        diag = c.diagnosis.strip().capitalize()
        if patient.age <= 12: ag = "0-12"
        elif patient.age <= 25: ag = "13-25"
        elif patient.age <= 40: ag = "26-40"
        elif patient.age <= 60: ag = "41-60"
        else: ag = "60+"
        if ag not in age_diagnosis:
            age_diagnosis[ag] = {}
        age_diagnosis[ag][diag] = age_diagnosis[ag].get(diag, 0) + 1
        g = patient.gender.capitalize()
        if g not in gender_diagnosis:
            gender_diagnosis[g] = {}
        gender_diagnosis[g][diag] = gender_diagnosis[g].get(diag, 0) + 1

    age_patterns = []
    for ag in ["0-12", "13-25", "26-40", "41-60", "60+"]:
        diags = age_diagnosis.get(ag, {})
        top = max(diags.items(), key=lambda x: x[1]) if diags else ("—", 0)
        age_patterns.append({
            "age_group": ag,
            "total_patients": age_groups[ag],
            "top_diagnosis": top[0],
            "cases": top[1]
        })

    gender_patterns = []
    for g in ["Male", "Female", "Other"]:
        total = gender_counts.get(g, 0)
        diags = gender_diagnosis.get(g, {})
        top = max(diags.items(), key=lambda x: x[1]) if diags else ("—", 0)
        gender_patterns.append({
            "gender": g,
            "total_patients": total,
            "top_diagnosis": top[0],
            "cases": top[1]
        })

    daily_counts = {}
    for c in all_consults:
        day = c.created_at.strftime("%d %b")
        daily_counts[day] = daily_counts.get(day, 0) + 1

    return {
        "overview": {
            "total_consultations": len(all_consults),
            "today_consultations": len(today_consults),
            "week_consultations": len(week_consults),
            "month_consultations": len(month_consults),
            "total_patients": len(all_patients),
            "new_patients_month": len(new_patients_month),
            "total_doctors": len(hospital_doctors),
            "active_doctors": len([d for d in hospital_doctors if d.is_active]),
            "otc_medicines": otc_count,
            "rx_medicines": rx_count,
            "voided_consultations": voided_consults,
            "void_rate": round(voided_consults / total_attempted * 100, 1) if total_attempted > 0 else 0,
            "new_patient_visits": new_patient_visits,
            "returning_patient_visits": returning_patient_visits
        },
        "doctor_stats": doctor_stats,
        "recent_consultations": recent_list,
        "patients": patients_list,
        "top_medicines": top_medicines_detailed,
        "top_tests": [{"name": k, "count": v} for k, v in top_tests],
        "top_diagnoses": [{"name": k, "count": v} for k, v in top_diagnoses],
        "demographics": {
            "age_groups": age_groups,
            "gender": gender_counts,
            "blood_groups": {bg: blood_groups.get(bg, 0) for bg in ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]},
            "age_patterns": age_patterns,
            "gender_patterns": gender_patterns
        },
        "daily_consultations": daily_counts
    }

@router.get("/admin-consultations")
def admin_consultations(
    from_date: str = None,
    to_date: str = None,
    doctor_id: int = None,
    page: int = 1,
    limit: int = 50,
    current_doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db)
):
    from datetime import datetime
    if current_doctor.role.value not in ["admin", "sub_admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    hospital_doctor_ids = [
        d.id for d in db.query(DoctorModel).filter(
            DoctorModel.hospital_id == current_doctor.hospital_id,
            DoctorModel.role.in_([UserRole.doctor, UserRole.sub_admin])
        ).all()
    ]

    query = db.query(Consultation).filter(
        Consultation.doctor_id.in_(hospital_doctor_ids),
        Consultation.token_number != None
    )

    if from_date:
        try:
            fd = datetime.strptime(from_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid from_date format. Use YYYY-MM-DD")
        query = query.filter(Consultation.created_at >= fd)

    if to_date:
        try:
            td = datetime.strptime(to_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid to_date format. Use YYYY-MM-DD")
        td = td.replace(hour=23, minute=59, second=59)
        query = query.filter(Consultation.created_at <= td)

    if from_date and to_date and fd > td:
        raise HTTPException(status_code=400, detail="from_date cannot be after to_date")

    if doctor_id:
        query = query.filter(Consultation.doctor_id == doctor_id)

    total = query.count()
    consults = (
        query
        .join(Patient, Consultation.patient_id == Patient.id)
        .join(DoctorModel, Consultation.doctor_id == DoctorModel.id)
        .with_entities(
            Consultation.token_number,
            Consultation.diagnosis,
            Consultation.created_at,
            Consultation.is_voided,
            Patient.name.label("patient_name"),
            Patient.patient_uid.label("patient_uid"),
            DoctorModel.title.label("doctor_title"),
            DoctorModel.name.label("doctor_name")
        )
        .order_by(Consultation.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    result = []
    for c in consults:
        result.append({
            "token": c.token_number,
            "patient_name": c.patient_name or "—",
            "patient_uid": c.patient_uid or "—",
            "doctor_name": f"{c.doctor_title} {c.doctor_name}" if c.doctor_name else "—",
            "diagnosis": c.diagnosis or "—",
            "date": c.created_at.strftime("%d %b %Y %I:%M %p"),
            "is_voided": c.is_voided
        })

    return {
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,
        "consultations": result
    }