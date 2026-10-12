from app.models.notification import Notification


def notify_admin_refund(db, refund, staff, patient_name=None, kind="paid"):
    """Tells admin a refund was paid (or closed unpaid) — who did it, how much,
    and why. Admin never pays refunds; this is their only touchpoint.
    Caller commits."""
    amt = f"Rs.{(refund.amount or 0):.2f}"
    patient = patient_name or "a patient"
    reason = refund.reason or "not given"
    if kind == "paid":
        title = f"Refund paid — {amt}"
        message = f"{staff.name} (reception) refunded {amt} to {patient} by {refund.channel}. Reason: {reason}"
        severity = "info"
    else:
        title = f"Refund not paid — {amt}"
        message = f"{staff.name} (reception) closed a pending {amt} refund for {patient} without paying it. Reason: {reason}"
        severity = "warning"
    db.add(Notification(
        hospital_id=refund.hospital_id, source_key=f"refund_{kind}:{refund.id}", type="refund_settled",
        severity=severity, title=title, message=message, link_type=None, link_id=refund.id, is_read=False,
    ))