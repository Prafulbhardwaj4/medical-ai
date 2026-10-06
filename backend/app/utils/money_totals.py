"""Single source of truth for "Collected" and "Billed" money numbers.

Collected = every rupee that actually came in, by PAYMENT date, minus refunds
            and approved OPD waivers.
Billed    = invoice value (pre-tax subtotal), by INVOICE date.

billing_today (admin.py), revenue history and day-end (billing.py) all call
these helpers, so the three screens can never disagree.
"""
from collections import defaultdict
from app.models.checkin import Checkin
from app.models.test_order import TestOrder
from app.models.opd_charge import OpdCharge
from app.models.medicine_order import MedicineOrder
from app.models.admission import Admission
from app.models.admission_deposit import AdmissionDeposit
from app.models.invoice import Invoice
from app.models.refund import Refund
from app.models.waiver_request import WaiverRequest
from app.utils.inventory import line_total


def collection_entries(db, hospital_id, start, end):
    """Money IN between start and end (naive IST datetimes, end exclusive).
    Each entry: {at, mode, category, amount}. Approved OPD waivers come back
    as negative "waivers" entries. Refunds are separate (see refund_rows)."""
    entries = []

    def add(at, mode, category, amount):
        if amount:
            entries.append({"at": at, "mode": mode or None, "category": category, "amount": round(float(amount), 2)})

    for c in db.query(Checkin).filter(
        Checkin.hospital_id == hospital_id, Checkin.is_paid == True,  # noqa: E712
        Checkin.paid_at >= start, Checkin.paid_at < end
    ).all():
        add(c.paid_at, c.payment_method, "consultation", c.consultation_fee or 0)

    # Tests: lab orders are the only source. OPD only (admission_id empty);
    # IPD tests are billed on the discharge bill, not paid at the counter.
    for t in db.query(TestOrder).filter(
        TestOrder.hospital_id == hospital_id, TestOrder.admission_id.is_(None),
        TestOrder.status != "payment_pending",
        TestOrder.paid_at >= start, TestOrder.paid_at < end
    ).all():
        add(t.paid_at, t.payment_method, "tests", t.price or 0)

    for ch in db.query(OpdCharge).filter(
        OpdCharge.hospital_id == hospital_id, OpdCharge.status == "paid", OpdCharge.amount > 0,
        OpdCharge.paid_at >= start, OpdCharge.paid_at < end
    ).all():
        add(ch.paid_at, ch.payment_method, "opd_charges", (ch.amount or 0) * (ch.quantity or 1))

    # Includes orders paid and LATER cancelled: their refund is netted
    # separately, so the original collection has to be counted too.
    for mo in db.query(MedicineOrder).filter(
        MedicineOrder.hospital_id == hospital_id,
        MedicineOrder.status.in_(["paid", "dispensed", "cancelled"]),
        MedicineOrder.paid_at != None,  # noqa: E711
        MedicineOrder.paid_at >= start, MedicineOrder.paid_at < end
    ).all():
        add(mo.paid_at, mo.payment_method, "pharmacy",
            line_total(mo.unit_price or 0, (mo.billed_quantity if mo.billed_quantity is not None else mo.quantity) or 0))

    for d in db.query(AdmissionDeposit).join(Admission, AdmissionDeposit.admission_id == Admission.id).filter(
        Admission.hospital_id == hospital_id,
        AdmissionDeposit.collected_at >= start, AdmissionDeposit.collected_at < end
    ).all():
        add(d.collected_at, d.payment_method, "ipd_topups" if d.note == "Top-up collected" else "ipd_deposits", d.amount or 0)

    for inv in db.query(Invoice).filter(
        Invoice.hospital_id == hospital_id, Invoice.generated_from == "admission_discharge",
        Invoice.generated_at >= start, Invoice.generated_at < end
    ).all():
        add(inv.generated_at, inv.payment_method, "ipd_settlements", inv.amount_collected or 0)

    # Approved OPD waivers reduce Collected. IPD waivers are not netted here:
    # the discharge settlement amount is already net of them.
    for w, pay_mode in db.query(WaiverRequest, Checkin.payment_method).outerjoin(
        Checkin, Checkin.id == WaiverRequest.checkin_id
    ).filter(
        WaiverRequest.hospital_id == hospital_id, WaiverRequest.status == "approved",
        WaiverRequest.admission_id.is_(None),
        WaiverRequest.resolved_at >= start, WaiverRequest.resolved_at < end
    ).all():
        add(w.resolved_at, pay_mode if pay_mode in ("cash", "card", "upi") else "cash", "waivers", -abs(w.amount or 0))

    return entries


def refund_rows(db, hospital_id, start, end):
    return db.query(Refund).filter(
        Refund.hospital_id == hospital_id,
        Refund.processed_at >= start, Refund.processed_at < end
    ).all()


def collected_summary(db, hospital_id, start, end):
    entries = collection_entries(db, hospital_id, start, end)
    waivers = round(-sum(e["amount"] for e in entries if e["category"] == "waivers"), 2)
    gross = round(sum(e["amount"] for e in entries if e["category"] != "waivers"), 2)
    refunds = round(sum((r.amount or 0) for r in refund_rows(db, hospital_id, start, end)), 2)
    return {"gross": gross, "waivers": waivers, "refunds": refunds, "net": round(gross - waivers - refunds, 2)}


def collected_by_day(db, hospital_id, start, end):
    """{date: net collected} for every day in [start, end) that had money move."""
    days = defaultdict(float)
    for e in collection_entries(db, hospital_id, start, end):
        days[e["at"].date()] += e["amount"]
    for r in refund_rows(db, hospital_id, start, end):
        days[r.processed_at.date()] -= (r.amount or 0)
    return {d: round(v, 2) for d, v in days.items()}


def _invoice_value(inv):
    return inv.subtotal if inv.subtotal is not None else (inv.grand_total or 0)


def billed_total(db, hospital_id, start, end):
    rows = db.query(Invoice).filter(
        Invoice.hospital_id == hospital_id,
        Invoice.generated_at >= start, Invoice.generated_at < end
    ).all()
    return round(sum(_invoice_value(i) for i in rows), 2)