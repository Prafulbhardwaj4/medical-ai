import math
from sqlalchemy.orm import Session
from app.models.hospital_medicine import HospitalMedicine
from app.models.medicine_batch import MedicineBatch


def calculate_prescribed_quantity(matched_medicine, times_per_day, duration_days):
    """
    Auto-prefill for MedicineOrder.quantity, always editable by pharmacy afterward.

    - If times_per_day and duration_days are both known: raw = times_per_day * duration_days,
      rounded UP to the nearest full pack_size for per_pack (strip-billed) medicines — matches
      how deduct_stock_fefo already rounds at dispense time, so the prefill agrees with what
      actually gets deducted.
    - If either is missing/null (SOS, ambiguous, not mentioned): prefill one full pack/strip
      for a matched per_pack medicine, or 1 unit for a matched per_unit medicine — never guess
      a specific dose count with no basis. Pharmacy must review either way.
    - If the medicine isn't matched to the catalog at all, pack size is unknown — leave
      quantity blank like before; pharmacy has to link it to the catalog first regardless.
    """
    if not matched_medicine:
        return None

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