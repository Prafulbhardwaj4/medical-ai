from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List
from app.database import get_db
from app.models.consultation import Consultation
from app.models.patient import Patient
from app.models.doctor import Doctor
from app.schemas.consultation import ConsultationOut, ConsultationHistoryItem, ConsultationStructured, MedicineItem
from app.utils.auth import get_current_doctor, now_ist, decode_access_token
from app.services.whisper import transcribe_audio
from app.services.groq_service import structure_transcript
from app.services.pdf_service import generate_prescription_pdf
from app.services.sms_service import send_sms
from app.services.sarvam_stream import stream_transcribe
from app.models.doctor import Doctor as DoctorModel
from app.config import settings
from sqlalchemy import exists
import json
import asyncio
from datetime import datetime
import pytz
from fastapi.responses import FileResponse
import os



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
            Patient.doctor_id.in_(hospital_doctor_ids)
        ).all()
        total_patients = len(patients)
    else:
        base = db.query(Consultation).filter(
            Consultation.doctor_id == current_doctor.id,
            Consultation.token_number != None,
            Consultation.is_voided == False
        )
        patients = db.query(Patient).filter(
            Patient.doctor_id == current_doctor.id
        ).all()
        total_patients = len(patients)

    total_consultations = base.count()

    # Consultations per day (last 30 days)
    all_consultations = base.order_by(Consultation.created_at).all()

    daily_counts = {}
    for c in all_consultations:
        day = c.created_at.strftime("%d %b")
        daily_counts[day] = daily_counts.get(day, 0) + 1

    # Age group distribution from patients
    patients = db.query(Patient).filter(Patient.doctor_id == current_doctor.id).all()
    age_groups = {"0-12": 0, "13-25": 0, "26-40": 0, "41-60": 0, "60+": 0}
    for p in patients:
        if p.age <= 12:
            age_groups["0-12"] += 1
        elif p.age <= 25:
            age_groups["13-25"] += 1
        elif p.age <= 40:
            age_groups["26-40"] += 1
        elif p.age <= 60:
            age_groups["41-60"] += 1
        else:
            age_groups["60+"] += 1

    # Gender distribution
    gender_counts = {}
    for p in patients:
        g = p.gender.capitalize()
        gender_counts[g] = gender_counts.get(g, 0) + 1

    # Top diagnoses
    diagnosis_counts = {}
    for c in all_consultations:
        if c.diagnosis:
            d = c.diagnosis.strip().lower().capitalize()
            diagnosis_counts[d] = diagnosis_counts.get(d, 0) + 1
    top_diagnoses = sorted(diagnosis_counts.items(), key=lambda x: x[1], reverse=True)[:8]

    # Top medicines
    medicine_counts = {}
    for c in all_consultations:
        meds = json.loads(c.medicines or "[]")
        for m in meds:
            name = m.get("name", "").strip().capitalize()
            if name:
                medicine_counts[name] = medicine_counts.get(name, 0) + 1
    top_medicines = sorted(medicine_counts.items(), key=lambda x: x[1], reverse=True)[:8]

    # OTC vs Rx ratio
    otc_count = 0
    rx_count = 0
    for c in all_consultations:
        meds = json.loads(c.medicines or "[]")
        for m in meds:
            if m.get("schedule") == "otc":
                otc_count += 1
            else:
                rx_count += 1

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
async def transcribe(
    patient_id: int,
    audio: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    patient = db.query(Patient).filter(
        Patient.id == patient_id,
        Patient.doctor_id == current_doctor.id
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

    doctor = db.query(DoctorModel).filter(
        DoctorModel.id == int(payload.get("sub"))
    ).first()
    if not doctor:
        await websocket.close(code=4001)
        return

    patient = db.query(Patient).filter(
        Patient.id == patient_id,
        Patient.doctor_id == doctor.id
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


@router.get("/history/{patient_id}", response_model=List[ConsultationHistoryItem])
def get_history(
    patient_id: int,
    db: Session = Depends(get_db),
    current_doctor: Doctor = Depends(get_current_doctor)
):
    patient = db.query(Patient).filter(
        Patient.id == patient_id,
        Patient.doctor_id == current_doctor.id
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    consultations = (
        db.query(Consultation)
        .filter(
            Consultation.patient_id == patient_id,
            Consultation.token_number != None,
            Consultation.is_voided == False
        )
        .order_by(desc(Consultation.created_at))
        .all()
    )
    return consultations

@router.get("/prescriptions/{token_number}.pdf")
def get_prescription_pdf(
    token_number: str,
    current_doctor: Doctor = Depends(get_current_doctor),
    db: Session = Depends(get_db)
):
    consultation = db.query(Consultation).filter(
        Consultation.token_number == token_number,
        Consultation.doctor_id == current_doctor.id,
        Consultation.is_voided == False
    ).first()

    if not consultation:
        raise HTTPException(status_code=404, detail="Prescription not found")

    pdf_path = os.path.join("prescriptions", f"{token_number}.pdf")
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF not found")

    return FileResponse(pdf_path, media_type="application/pdf", filename=f"{token_number}.pdf")


@router.get("/verify/{token_number}")
def verify_prescription(token_number: str, hash: str, db: Session = Depends(get_db)):
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
def mark_dispensed(token_number: str, hash: str, db: Session = Depends(get_db)):
    consultation = db.query(Consultation).filter(
        Consultation.token_number == token_number,
        Consultation.verify_hash == hash
    ).first()

    if not consultation:
        raise HTTPException(status_code=404, detail="Invalid token or verification code")

    if consultation.is_dispensed:
        raise HTTPException(status_code=400, detail="Already marked as dispensed")

    consultation.is_dispensed = True
    consultation.dispensed_at = now_ist()
    db.commit()

    return {"message": "Marked as dispensed", "dispensed_at": consultation.dispensed_at.isoformat()}


@router.post("/structure/{consultation_id}")
async def structure(
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
def confirm_prescription(
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
    if not consultation.medicines:
        raise HTTPException(status_code=400, detail="Consultation not structured yet. Run /structure first.")
    if consultation.token_number:
        raise HTTPException(status_code=400, detail="Prescription already confirmed.")

    patient = db.query(Patient).filter(Patient.id == consultation.patient_id).first()

    prefix = "".join([w[0].upper() for w in current_doctor.clinic_name.split()][:3])
    date_str = now_ist().strftime("%d%m%y")
    confirmed_count = db.query(Consultation).filter(
        Consultation.doctor_id == current_doctor.id,
        Consultation.token_number != None
    ).count()
    token_number = f"{prefix}-{confirmed_count + 1:04d}-{date_str}"

    while db.query(Consultation).filter(Consultation.token_number == token_number).first():
        import random
        token_number = f"{prefix}-{confirmed_count + 1:04d}-{date_str}-{random.randint(10,99)}"

    consultation.token_number = token_number

    import hashlib
    hash_input = f"{token_number}-{current_doctor.id}-{consultation.id}-{settings.SECRET_KEY}"
    verify_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:8].upper()
    consultation.verify_hash = verify_hash

    try:
        pdf_path = generate_prescription_pdf(current_doctor, patient, consultation, token_number, verify_hash)
        consultation.pdf_path = pdf_path
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)}")

    db.commit()
    db.refresh(consultation)

    return {
        "consultation_id": consultation.id,
        "token_number": token_number,
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
    return {"message": "Consultation voided"}


@router.post("/send-sms/{consultation_id}")
def send_prescription_sms(
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