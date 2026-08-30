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
        for hospital in hospitals:
            if is_past_grace(hospital, now):
                hospital.is_active = False
                logger.info(f"Auto-deactivated hospital {hospital.id} ({hospital.name}) — grace window passed with no renewal.")
        db.commit()
    finally:
        db.close()


def _seconds_until_next_midnight_ist():
    now = now_ist()
    tomorrow_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (tomorrow_midnight - now).total_seconds()


def run_midnight_close_for_all_hospitals():
    from app.routers.billing import close_day_for_hospital  # local import avoids a circular import at module load time

    db = SessionLocal()
    try:
        yesterday = ist_today() - timedelta(days=1)
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


async def midnight_close_loop():
    while True:
        try:
            wait_seconds = _seconds_until_next_midnight_ist()
            await asyncio.sleep(wait_seconds)
            run_midnight_close_for_all_hospitals()
            run_billing_deactivation_sweep_for_all_hospitals()
        except Exception as e:
            logger.warning(f"Midnight scheduler loop error: {e}")
            await asyncio.sleep(60)  # avoid a tight crash loop if something above is broken