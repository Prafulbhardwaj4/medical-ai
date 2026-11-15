"""Central retention settings and purge jobs (Phase 7).

Everything that deletes medical data is OFF by default (0 days). Medical records, audit rows and
deactivated hospitals' data are never deleted here.
"""
import logging
import os
import time
from datetime import timedelta

from app.config import settings
from app.database import SessionLocal
from app.utils.timezone import now_ist_naive

log = logging.getLogger(__name__)

SECRET_ROW_KEEP_DAYS = 7  # a used / expired / cancelled secret message row is removed after this long
UNSENT_STATUSES = ("scheduled", "due", "pending")


def raw_transcript_days() -> int:
    return max(int(settings.RAW_TRANSCRIPT_RETENTION_DAYS or 0), 0)


def chat_upload_days() -> int:
    return max(int(settings.CHAT_UPLOAD_RETENTION_DAYS or 0), 0)


def whatsapp_message_days() -> int:
    return max(int(settings.WHATSAPP_MESSAGE_RETENTION_DAYS or 0), 0)


def purge_raw_transcripts(db) -> int:
    """Sets raw_transcript to NULL for confirmed consultations older than RAW_TRANSCRIPT_RETENTION_DAYS."""
    days = raw_transcript_days()
    if not days:
        return 0
    from app.models.consultation import Consultation
    cutoff = now_ist_naive() - timedelta(days=days)
    total = 0
    for _ in range(40):
        ids = [r[0] for r in db.query(Consultation.id).filter(
            Consultation.token_number.isnot(None),
            Consultation.raw_transcript.isnot(None),
            Consultation.created_at < cutoff,
        ).limit(500).all()]
        if not ids:
            break
        db.query(Consultation).filter(Consultation.id.in_(ids)).update(
            {Consultation.raw_transcript: None}, synchronize_session=False)
        db.commit()
        total += len(ids)
    return total


def purge_whatsapp_messages(db) -> int:
    """Removes old WhatsApp message rows (never unsent ones) and finished secret rows."""
    from app.models.whatsapp_message import WhatsappMessage
    now = now_ist_naive()
    total = 0
    days = whatsapp_message_days()
    conditions = []
    if days:
        conditions.append(("old", [WhatsappMessage.created_at < now - timedelta(days=days),
                                   WhatsappMessage.status.notin_(UNSENT_STATUSES)]))
    conditions.append(("secret", [WhatsappMessage.is_secret == True,  # noqa: E712
                                  WhatsappMessage.status.in_(("sent", "expired", "cancelled")),
                                  WhatsappMessage.created_at < now - timedelta(days=SECRET_ROW_KEEP_DAYS)]))
    for _name, conds in conditions:
        for _ in range(40):
            ids = [r[0] for r in db.query(WhatsappMessage.id).filter(*conds).limit(500).all()]
            if not ids:
                break
            db.query(WhatsappMessage).filter(WhatsappMessage.id.in_(ids)).delete(synchronize_session=False)
            db.commit()
            total += len(ids)
    return total


def purge_chat_uploads() -> int:
    """Deletes chat attachment files older than CHAT_UPLOAD_RETENTION_DAYS. Radiology reports are never touched."""
    days = chat_upload_days()
    if not days:
        return 0
    from app.services import storage
    cutoff = time.time() - days * 86400
    removed = 0
    for key, modified in storage.list_keys(storage.CHAT_PREFIX):
        try:
            if modified < cutoff:
                storage.delete(key)
                removed += 1
        except Exception as e:
            log.warning("Could not remove chat upload %s: %s", key, e)
    return removed


def run_all() -> dict:
    """Runs every enabled purge. One job failing never stops the others."""
    result = {}
    db = SessionLocal()
    try:
        for name, job in (("raw_transcripts", purge_raw_transcripts), ("whatsapp_messages", purge_whatsapp_messages)):
            try:
                result[name] = job(db)
            except Exception as e:
                db.rollback()
                log.warning("Retention job %s failed: %s", name, e)
    finally:
        db.close()
    try:
        result["chat_uploads"] = purge_chat_uploads()
    except Exception as e:
        log.warning("Retention job chat_uploads failed: %s", e)
    if any(result.values()):
        log.info("Retention purge removed: %s", result)
    return result