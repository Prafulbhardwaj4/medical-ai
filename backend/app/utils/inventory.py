import math
from sqlalchemy.orm import Session
from app.models.hospital_medicine import HospitalMedicine
from app.models.medicine_batch import MedicineBatch

# Non-countable dosage forms — "3x/day for 3 days" doesn't mean 9 units for these, since a
# single bottle/tube/vial covers many doses. Everything NOT in this set (including blank/
# unset dosage_forms, which most existing catalog entries have since the field isn't
# required) is treated as countable and gets the old times_per_day x duration_days
# multiply — that was already correct for tablets/capsules and is the safer default for
# anything unlabeled, since most medicines in practice are discrete-unit forms.
NON_COUNTABLE_FORMS = {"Syrup", "Suspension", "Injection", "Drops", "Ointment", "Cream", "Gel", "Lotion", "Inhaler", "Spray", "Powder"}


def calculate_prescribed_quantity(matched_medicine, times_per_day, duration_days):
    """
    Auto-prefill for MedicineOrder.quantity, always editable by pharmacy afterward.

    - Countable forms (tablet/capsule/sachet/suppository/patch): raw = times_per_day *
      duration_days when both are known, rounded UP to the nearest full pack_size for
      per_pack (strip-billed) medicines — matches how deduct_stock_fefo rounds at dispense
      time. If frequency/duration is missing (SOS, ambiguous), falls back to one pack/strip
      or 1 unit — never guesses a specific dose count with no basis.
    - Non-countable forms (syrup, suspension, injection, drops, ointment, cream, gel,
      lotion, inhaler, spray, powder, or anything typed in via "Other"): quantity is not a
      simple multiple of dose count (a "3x/day for 3 days" syrup isn't 9 bottles). Always
      defaults to 1; pharmacy manually increases it if more than one bottle/vial/tube is
      actually needed.
    - If the medicine isn't matched to the catalog at all, dosage form is unknown — leave
      quantity blank; pharmacy has to link it to the catalog first regardless.
    """
    if not matched_medicine:
        return None

    if matched_medicine.dosage_forms in NON_COUNTABLE_FORMS:
        return 1

    pack_size = matched_medicine.pack_size or 1
    is_per_pack = matched_medicine.billing_mode == "per_pack"

    if times_per_day and duration_days and times_per_day > 0 and duration_days > 0:
        raw = int(math.ceil(times_per_day * duration_days))
        if is_per_pack and pack_size > 1:
            return int(math.ceil(raw / pack_size) * pack_size)
        return raw

    return pack_size if is_per_pack else 1

def deduct_stock_fefo(db: Session, medicine_id: int, quantity_needed: int) -> dict:
    """
    Deducts `quantity_needed` units from a medicine's stock, consuming the
    soonest-expiring batches first (FEFO — First-Expiry-First-Out).

    If the medicine is billed per_pack (whole strips only, never split), the
    deduction is rounded UP to the next full pack_size before touching stock —
    e.g. dispensing 9 tablets from a 10-per-strip per_pack medicine removes a
    full strip of 10, not 9, since that strip physically can't go back once opened.
    per_unit-billed medicines deduct the exact quantity, unchanged.

    The aggregate stock_quantity always drops by the full (possibly rounded)
    quantity, floored at 0. Batch rows are decremented for as much as they can
    cover; any shortfall just means older/legacy stock (added before batch
    tracking existed) is being consumed — reported back for visibility, but
    never blocks the dispense. Patient care should never wait on inventory bookkeeping.
    """
    medicine = db.query(HospitalMedicine).filter(HospitalMedicine.id == medicine_id).first()
    if not medicine:
        return {"medicine_id": medicine_id, "medicine_name": None, "deducted_from_batches": 0, "shortfall": quantity_needed}

    if medicine.billing_mode == "per_pack" and medicine.pack_size and medicine.pack_size > 1:
        pack_size = medicine.pack_size
        quantity_needed = ((quantity_needed + pack_size - 1) // pack_size) * pack_size  # round up to next full strip

    remaining = quantity_needed
    deducted_from_batches = 0

    batches = db.query(MedicineBatch).filter(
        MedicineBatch.medicine_id == medicine_id,
        MedicineBatch.quantity > 0
    ).order_by(MedicineBatch.expiry_date.asc().nullslast()).all()

    for batch in batches:
        if remaining <= 0:
            break
        take = min(batch.quantity, remaining)
        batch.quantity -= take
        remaining -= take
        deducted_from_batches += take

    medicine.stock_quantity = max(0, (medicine.stock_quantity or 0) - quantity_needed)

    return {
        "medicine_id": medicine_id,
        "medicine_name": medicine.generic_name,
        "deducted_from_batches": deducted_from_batches,
        "shortfall": remaining  # >0 means batch records under-counted actual stock (legacy/untracked stock consumed)
    }