"""
GST computation for billing — kept in one shared place so OPD invoices
(billing.py) and IPD discharge invoices (admissions.py) can never compute
tax differently from each other.

Every rate is nullable on the Hospital record and blank = 0% by design:
nothing is taxed until a rate is explicitly set. This is intentional — GST
is being wired in ahead of a CA/lawyer sign-off, so leaving rates blank
keeps every invoice generated between now and that review byte-for-byte
identical to today. Only room_gst_threshold_per_day has a non-null default
(Rs.5000/day), since it's a structural switch, not a tax rate.

Rates are captured into each invoice line at the moment the invoice is
generated (frozen into items_json), not recomputed later — editing a
hospital's rate afterwards never rewrites a past invoice.

ASSUMPTION FLAGGED FOR LAWYER/CA REVIEW: this treats every patient as
intra-state and splits tax evenly into CGST + SGST. There is no
patient/hospital "which state" field anywhere in the schema to detect an
inter-state (IGST) case. If any hospital on this platform routinely bills
out-of-state patients, that needs a real fix before launch.
"""


def _rate_for(item_type: str, hospital) -> float:
    if item_type == "consultation":
        return hospital.consultation_gst_percent or 0.0
    if item_type == "test":
        return hospital.test_gst_percent or 0.0
    if item_type == "room":
        return hospital.room_gst_percent or 0.0
    return hospital.charge_gst_percent or 0.0  # consumable / procedure / other / professional_fee / OPD charge


def _hsn_for(item_type: str, hospital, medicine_hsn: str = None) -> str:
    """HSN (goods) / SAC (services) code for a line item — GST-mandatory on
    a tax invoice. Medicines carry their own per-drug code (varies by
    product); every other item type uses the hospital's configured default
    for that category."""
    if item_type == "medicine":
        return medicine_hsn or None
    if item_type == "consultation":
        return hospital.hsn_consultation or None
    if item_type == "test":
        return hospital.hsn_test or None
    if item_type == "room":
        return hospital.hsn_room or None
    return hospital.hsn_charge or None  # consumable / procedure / other / professional_fee / OPD charge


def apply_gst(items: list, hospital) -> tuple:
    """Returns (items_with_tax, subtotal, gst_total, grand_total).

    Each returned item keeps its original keys and gains: gst_rate,
    taxable_amount, tax_amount, cgst_amount, sgst_amount, total_with_tax.

    If the hospital has no GSTIN on file, every item is forced exempt
    regardless of configured rates — an unregistered hospital cannot
    legally charge GST. Items marked payable_here=False (e.g. IPD pharmacy
    lines settled at the pharmacy counter, not on this bill) are never taxed
    here either, since they're not actually being charged on this invoice.
    """
    gst_registered = bool(hospital and hospital.gstin)
    out = []
    subtotal = 0.0
    gst_total = 0.0

    for item in items:
        line_total = item.get("line_total", 0.0)
        subtotal += line_total
        payable_here = item.get("payable_here", True)

        if not gst_registered or not payable_here:
            rate, taxable, tax = 0.0, 0.0, 0.0
        elif item["type"] == "room":
            # Current law (Notification 12/2017, as amended 2022): a non-ICU room's
            # daily rate crossing the threshold makes the ENTIRE room charge taxable
            # for that stay, not just the amount above the threshold. ICU/CCU/ICCU/NICU
            # wards (ward_type.is_icu) are exempt regardless of rate.
            threshold = hospital.room_gst_threshold_per_day or 0.0
            daily_rate = item.get("unit_price", 0.0)
            is_icu = item.get("_is_icu", False)
            rate = hospital.room_gst_percent or 0.0
            if is_icu or daily_rate <= threshold:
                rate, taxable, tax = 0.0, 0.0, 0.0
            else:
                taxable = round(line_total, 2)
                tax = round(taxable * rate / 100, 2) if rate else 0.0
        elif item["type"] == "medicine":
            rate = item.get("_medicine_gst_percent") or 0.0
            taxable = line_total if rate else 0.0
            tax = round(taxable * rate / 100, 2) if rate else 0.0
        else:
            rate = _rate_for(item["type"], hospital)
            taxable = line_total if rate else 0.0
            tax = round(taxable * rate / 100, 2) if rate else 0.0

        hsn_sac = (_hsn_for(item["type"], hospital, item.get("_medicine_hsn_code")) or "") if gst_registered else ""

        gst_total += tax
        clean_item = {k: v for k, v in item.items() if k not in ("_medicine_gst_percent", "_medicine_hsn_code", "_is_icu")}
        out.append({
            **clean_item,
            "hsn_sac": hsn_sac,
            "gst_rate": rate,
            "taxable_amount": taxable,
            "tax_amount": tax,
            "cgst_amount": round(tax / 2, 2),
            "sgst_amount": round(tax / 2, 2),
            "total_with_tax": round(line_total + tax, 2),
        })

    subtotal = round(subtotal, 2)
    gst_total = round(gst_total, 2)
    grand_total = round(subtotal + gst_total, 2)
    return out, subtotal, gst_total, grand_total