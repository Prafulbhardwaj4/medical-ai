"""Visit / token WhatsApp message for every reception visit (and, in the next phase, for online
appointments: the same message, the same token). The TEXT lives only in whatsapp_messages.py."""
import logging

from sqlalchemy.orm import Session

from app.services import whatsapp_messages as wa
from app.utils.timezone import now_ist_naive

logger = logging.getLogger("whatsapp")


def queue_visit_token_message(db: Session, *, checkin, patient, doctor, hospital, created_by=None) -> bool:
    """Adds the token message (due immediately) for one check-in and commits it.
    The business action is already saved before this runs, and a failure here is only logged."""
    try:
        if checkin is None or patient is None or not (patient.phone or "").strip():
            return False
        with db.begin_nested():
            wa.enqueue_message(
                db,
                template_key=wa.T_VISIT_TOKEN,
                text=wa.build_visit_token(
                    patient_name=patient.name,
                    hospital_name=hospital.name if hospital else "",
                    token_number=checkin.token_number,
                    doctor_name=f"{doctor.title or ''} {doctor.name}".strip() if doctor else "",
                    speciality=getattr(doctor, "specialization", None) if doctor else None,
                    room=checkin.doctor_room,
                    visit_datetime=checkin.created_at or now_ist_naive(),
                    patient_uid=patient.patient_uid,
                    hospital_mobile_number=wa.hospital_mobile(hospital),
                ),
                hospital_id=checkin.hospital_id,
                recipient_kind="patient",
                recipient_id=patient.id,
                recipient_name=patient.name,
                recipient_role="patient",
                recipient_phone=patient.phone,
                visibility=wa.VIS_ALL,
                created_by=created_by,
                checkin_id=checkin.id,
                token_number=checkin.token_number,
            )
        db.commit()
        return True
    except Exception:
        logger.exception("Could not queue the visit token message")
        try:
            db.rollback()
        except Exception:
            pass
        return False