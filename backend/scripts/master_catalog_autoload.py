"""Start-up top-up of the platform-wide MASTER test and medicine lists (same idea as the tutorial seeder:
Render's free tier has no shell, so a manual script can never reach production).
Source of truth: scripts/master_data_tests.py and scripts/master_data_medicines.py.
It only ADDS items that are missing (tests matched by name, medicines by generic + strength + form).
It never edits, re-activates or deletes anything, so Super Admin changes and deactivations are kept.
If any item in the data files is invalid, NOTHING is saved and the problems are logged."""
import logging

from fastapi import HTTPException

from app.database import SessionLocal
from app.models.master_medicine import MasterMedicine
from app.models.master_test import MasterTest, MasterTestParameter
from app.services.master_catalog_service import (
    MasterMedicineIn, MasterTestIn, clean_medicine_payload, clean_test_payload, medicine_conflict, test_name_conflict,
)
from scripts.master_data_medicines import MASTER_MEDICINES
from scripts.master_data_tests import MASTER_TESTS

log = logging.getLogger(__name__)


def _problem(label, exc):
    return f"{label}: {exc.detail if isinstance(exc, HTTPException) else exc}"


def run():
    problems, tests, meds = [], [], []
    for raw in MASTER_TESTS:
        try:
            tests.append(clean_test_payload(MasterTestIn(**raw)))
        except Exception as e:  # noqa: BLE001
            problems.append(_problem(f"Test '{raw.get('test_name', '?')}'", e))
    for raw in MASTER_MEDICINES:
        try:
            meds.append(clean_medicine_payload(MasterMedicineIn(**raw)))
        except Exception as e:  # noqa: BLE001
            problems.append(_problem(f"Medicine '{raw.get('generic_name', '?')} {raw.get('strength', '')}'", e))
    if problems:
        log.error("Master list auto-load skipped, nothing saved: %s", "; ".join(problems[:10]))
        return
    db = SessionLocal()
    added_t = added_m = 0
    try:
        for c in tests:
            if test_name_conflict(db, c["name"]):
                continue
            params = c.pop("params")
            t = MasterTest(is_active=True, **c)
            db.add(t)
            db.flush()
            for p in params:
                db.add(MasterTestParameter(master_test_id=t.id, is_active=True, **p))
            added_t += 1
        for c in meds:
            if medicine_conflict(db, c["generic_name"], c["strength"], c["dosage_form"]):
                continue
            db.add(MasterMedicine(is_active=True, **c))
            db.flush()
            added_m += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    if added_t or added_m:
        log.info("Master list auto-load: %s tests and %s medicines added.", added_t, added_m)