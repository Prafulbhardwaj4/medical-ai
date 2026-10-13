"""Loads (or tops up) the platform-wide MASTER test and medicine lists from
scripts/master_data_tests.py and scripts/master_data_medicines.py.

Run from the Backend folder, against the database your .env points to:

    python scripts/load_master_catalog.py

Safe to run again and again: it only ADDS items that are missing (tests matched by name, medicines by
generic + strength + form). It never changes, deactivates or deletes anything already in the master list,
and it never touches any hospital data. Every item is checked with the same rules as the Super Admin forms;
if even one item is invalid, NOTHING is saved and the problems are printed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app.main  # noqa: E402,F401  (makes sure every model is registered)
from fastapi import HTTPException  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.master_medicine import MasterMedicine  # noqa: E402
from app.models.master_test import MasterTest, MasterTestParameter  # noqa: E402
from app.services.master_catalog_service import (  # noqa: E402
    MasterMedicineIn, MasterTestIn, clean_medicine_payload, clean_test_payload, medicine_conflict, test_name_conflict,
)
from master_data_medicines import MASTER_MEDICINES  # noqa: E402
from master_data_tests import MASTER_TESTS  # noqa: E402


def _problem(label, exc):
    detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
    return f"{label}: {detail}"


def main():
    problems, tests, meds = [], [], []
    for raw in MASTER_TESTS:
        label = f"Test '{raw.get('test_name', '?')}'"
        try:
            tests.append(clean_test_payload(MasterTestIn(**raw)))
        except Exception as e:  # noqa: BLE001
            problems.append(_problem(label, e))
    for raw in MASTER_MEDICINES:
        label = f"Medicine '{raw.get('generic_name', '?')} {raw.get('strength', '')} {raw.get('dosage_form', '')}'"
        try:
            meds.append(clean_medicine_payload(MasterMedicineIn(**raw)))
        except Exception as e:  # noqa: BLE001
            problems.append(_problem(label, e))
    if problems:
        print("NOTHING WAS SAVED. Fix these first:")
        for p in problems:
            print(" -", p)
        sys.exit(1)

    db = SessionLocal()
    added_t = skipped_t = added_m = skipped_m = 0
    try:
        for c in tests:
            if test_name_conflict(db, c["name"]):
                skipped_t += 1
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
                skipped_m += 1
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
    print(f"Master tests:     {added_t} added, {skipped_t} already there.")
    print(f"Master medicines: {added_m} added, {skipped_m} already there.")


if __name__ == "__main__":
    main()