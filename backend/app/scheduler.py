"""Lightweight in-process scheduler — no extra service/cron dependency.

Runs one background asyncio task for the life of the app that sleeps until
the next midnight IST, then closes yesterday's day-end for every hospital
that had activity and wasn't already closed, then goes back to sleep for
the next midnight. This replaces relying on someone opening the Day End
Close screen the next day to trigger the lazy catch-up in billing.py —
that catch-up still exists as a safety net for whenever the process was
down at midnight (e.g. a deploy), so the two work together rather than
one replacing the other.
"""
import asyncio
import logging
from datetime import timedelta

from app.database import SessionLocal
from app.models.hospital import Hospital
from app.models.day_end_close import DayEndClose
from app.utils.timezone import ist_today, now_ist, now_ist_naive
from app.utils.billing_cycle import is_past_grace
from app.utils.audit import log_action

logger = logging.getLogger("scheduler")


def run_billing_deactivation_sweep_for_all_hospitals():
    """Item 4/7: once a hospital's grace window has fully passed with no
    renewal, the whole account is deactivated. Runs once daily alongside
    the midnight day-end close — day-level granularity is fine here since
    every date in the spec (cycle-end, grace-end, deactivation date) is
    itself a whole day, not a specific time. The AI-Scribe-stops-at-
    cycle-end part is enforced live on every /structure call via
    is_ai_scribe_period_active, independent of this sweep."""
    db = SessionLocal()
    try:
        now = now_ist_naive()
        hospitals = db.query(Hospital).filter(
            Hospital.is_active == True,  # noqa: E712
            Hospital.billing_cycle_start.isnot(None),
        ).all()
        deactivated = []
        for hospital in hospitals:
            if is_past_grace(hospital, now):
                hospital.is_active = False
                logger.info(f"Auto-deactivated hospital {hospital.id} ({hospital.name}) — grace window passed with no renewal.")
                deactivated.append(hospital)
        db.commit()
        for hospital in deactivated:
            log_action(
                db, None,
                action="hospital_auto_deactivated",
                target_type="hospital", target_id=hospital.id, target_label=hospital.name,
                details="Grace window passed with no renewal",
                hospital_id=hospital.id
            )
    finally:
        db.close()


GENERATED_PDF_MAX_AGE_DAYS = 3


def purge_generated_files():
    """Deletes generated PDFs older than GENERATED_PDF_MAX_AGE_DAYS. Each one is rebuilt
    from the database the next time it is opened. Never touches chat_uploads (those
    cannot be rebuilt) or radiology reports."""
    import os
    import time
    backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    cutoff = time.time() - GENERATED_PDF_MAX_AGE_DAYS * 86400
    removed = 0
    for sub in ("prescriptions", "reports", "token_slips", "invoices"):
        folder = os.path.join(backend_dir, sub)
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            if not name.lower().endswith(".pdf") or name.startswith("radiology_report_"):
                continue
            path = os.path.join(folder, name)
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed += 1
            except OSError as e:
                logger.warning(f"Could not remove {path}: {e}")
    if removed:
        logger.info(f"Generated-file cleanup removed {removed} old PDF(s).")


def _seconds_until_next_midnight_ist():
    now = now_ist()
    tomorrow_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (tomorrow_midnight - now).total_seconds()


def run_midnight_close_for_all_hospitals():
    """Closes yesterday and any earlier unclosed day (up to 14 back, e.g. after downtime)."""
    for days_back in range(14, 0, -1):
        _close_day_for_all_hospitals(ist_today() - timedelta(days=days_back))


def _close_day_for_all_hospitals(yesterday):
    from app.routers.billing import close_day_for_hospital  # local import avoids a circular import at module load time

    db = SessionLocal()
    try:
        hospital_ids = [h.id for h in db.query(Hospital.id).all()]
        for hospital_id in hospital_ids:
            already = db.query(DayEndClose).filter(
                DayEndClose.hospital_id == hospital_id, DayEndClose.close_date == yesterday
            ).first()
            if already:
                continue
            try:
                close_day_for_hospital(
                    db, hospital_id, yesterday, closed_by=None,
                    note="Auto-closed by the midnight scheduler — no manual count was entered before day rollover.",
                )
            except Exception as e:
                logger.warning(f"Midnight day-end close failed for hospital {hospital_id}: {e}")
    finally:
        db.close()


_last_draft_purge = now_ist_naive()


def purge_abandoned_drafts():
    """Deletes unconfirmed consultation drafts (no prescription token) older than 7 days, so
    old transcripts of patient conversations do not pile up. Confirmed consultations are never touched."""
    from app.models.consultation import Consultation
    from app.models.doctor import Doctor

    db = SessionLocal()
    try:
        cutoff = now_ist_naive() - timedelta(days=7)
        drafts = db.query(Consultation).filter(
            Consultation.token_number == None,  # noqa: E711
            Consultation.created_at < cutoff,
        ).limit(200).all()
        for d in drafts:
            try:
                db.query(Doctor).filter(Doctor.active_consultation_id == d.id).update(
                    {Doctor.active_consultation_id: None}, synchronize_session=False
                )
                db.delete(d)
                db.commit()
            except Exception as e:
                db.rollback()  # still referenced by an order, so leave it alone
                logger.warning(f"Draft purge skipped consultation {d.id}: {e}")
    finally:
        db.close()


def run_lab_escalation_tick():
    """Idempotent: critical-result escalation and uncollected IPD-sample pings for
    every active hospital, so they fire after hours too (not only when someone loads the lab queue)."""
    from app.routers.lab import _escalate_unacknowledged_critical_results, _escalate_uncollected_admission_samples

    db = SessionLocal()
    try:
        hospital_ids = [h.id for h in db.query(Hospital.id).filter(Hospital.is_active == True).all()]  # noqa: E712
        for hospital_id in hospital_ids:
            try:
                _escalate_unacknowledged_critical_results(db, hospital_id)
                _escalate_uncollected_admission_samples(db, hospital_id)
                global _last_draft_purge
                if (now_ist_naive() - _last_draft_purge).total_seconds() > 3600:
                    _last_draft_purge = now_ist_naive()
                    purge_abandoned_drafts()
                from app.routers.attendance import auto_close_stale_shifts
                auto_close_stale_shifts(db, hospital_id)  # shift auto-close + idle-staff alerts, off the request path
            except Exception as e:
                db.rollback()
                logger.warning(f"Lab escalation tick failed for hospital {hospital_id}: {e}")
    finally:
        db.close()


async def lab_escalation_loop():
    while True:
        try:
            await asyncio.sleep(120)
            await asyncio.get_running_loop().run_in_executor(None, run_lab_escalation_tick)
        except Exception as e:
            logger.warning(f"Lab escalation loop error: {e}")
            await asyncio.sleep(60)


async def midnight_close_loop():
    try:
        run_midnight_close_for_all_hospitals()  # catch up on any day missed while the server was down
        purge_generated_files()
    except Exception as e:
        logger.warning(f"Startup day-end catch-up failed: {e}")
    while True:
        try:
            wait_seconds = _seconds_until_next_midnight_ist()
            await asyncio.sleep(wait_seconds)
            purge_generated_files()
            run_midnight_close_for_all_hospitals()
            run_billing_deactivation_sweep_for_all_hospitals()
        except Exception as e:
            logger.warning(f"Midnight scheduler loop error: {e}")
            await asyncio.sleep(60)  # avoid a tight crash loop if something above is broken