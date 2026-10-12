"""Single source of truth for "Collected" and "Billed" money numbers.

Collected = every rupee that actually came in, by PAYMENT date, minus refunds
            and approved OPD waivers.
Billed    = invoice value (pre-tax subtotal), by INVOICE date.

billing_today (admin.py), revenue history and day-end (billing.py) all call
these helpers, so the three screens can never disagree.
"""
from collections import defaultdict
from sqlalchemy import func
from app.models.checkin import Checkin
from app.models.portal import Appointment
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

    _checkins = db.query(Checkin).filter(
        Checkin.hospital_id == hospital_id, Checkin.is_paid == True,  # noqa: E712
        Checkin.paid_at >= start, Checkin.paid_at < end
    ).all()
    # A check-in made from an appointment carries the same fee the appointment
    # itself records, so that fee is counted once, from the appointment, below.
    _linked = {c.portal_appointment_id for c in _checkins if c.portal_appointment_id}
    _counted_via_appt = {
        i for (i,) in db.query(Appointment.id).filter(
            Appointment.id.in_(_linked), Appointment.payment_status == "paid", Appointment.paid_at.isnot(None)
        ).all()
    } if _linked else set()
    for c in _checkins:
        if c.portal_appointment_id in _counted_via_appt:
            continue
        add(c.paid_at, c.payment_method, "consultation", c.consultation_fee or 0)

    # Appointment fees collected at reception count on the day the money was
    # taken, whether or not the patient ever got a token (no-shows, future
    # dates, new patients). Refunds of these fees are netted separately.
    for ap in db.query(Appointment).filter(
        Appointment.hospital_id == hospital_id, Appointment.payment_status == "paid",
        Appointment.paid_at >= start, Appointment.paid_at < end
    ).all():
        add(ap.paid_at, ap.payment_method, "consultation", ap.fee_amount or 0)

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
    """Paid-out refunds, placed on the day the ORIGINAL money was collected
    (collected_at), not the day they were paid back. Pending/dismissed
    refunds have moved no money, so they never count."""
    on_day = func.coalesce(Refund.collected_at, Refund.processed_at)
    return db.query(Refund).filter(
        Refund.hospital_id == hospital_id,
        Refund.status == "completed",
        on_day >= start, on_day < end
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
        days[(r.collected_at or r.processed_at).date()] -= (r.amount or 0)
    return {d: round(v, 2) for d, v in days.items()}


def uninvoiced_appointment_fees(db, hospital_id, start, end):
    """[(paid_at, amount)] for appointment fees collected between start and end
    whose visit has no invoice yet. They count as Billed on the day collected;
    once the visit's invoice exists, the invoice carries the fee instead."""
    appts = db.query(Appointment).filter(
        Appointment.hospital_id == hospital_id, Appointment.payment_status == "paid",
        Appointment.paid_at >= start, Appointment.paid_at < end
    ).all()
    appts = [a for a in appts if a.fee_amount]
    if not appts:
        return []
    invoiced_ids = {
        i for (i,) in db.query(Checkin.portal_appointment_id).filter(
            Checkin.portal_appointment_id.in_([a.id for a in appts]), Checkin.invoice_id.isnot(None)
        ).all()
    }
    return [(a.paid_at, round(float(a.fee_amount), 2)) for a in appts if a.id not in invoiced_ids]


def _invoice_value(inv):
    return inv.subtotal if inv.subtotal is not None else (inv.grand_total or 0)


def billed_total(db, hospital_id, start, end):
    rows = db.query(Invoice).filter(
        Invoice.hospital_id == hospital_id,
        Invoice.generated_at >= start, Invoice.generated_at < end
    ).all()
    invoiced = sum(_invoice_value(i) for i in rows)
    uninvoiced = sum(amt for _, amt in uninvoiced_appointment_fees(db, hospital_id, start, end))
    return round(invoiced + uninvoiced, 2)