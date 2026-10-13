"""MASTER MEDICINE LIST (platform-wide). One tuple per medicine; no prices, no brands, no stock.
Add a medicine by adding one line, then run:  python scripts/load_master_catalog.py
The loader only ADDS medicines that are not already in the master list (same generic + strength + form);
it never changes or deletes one. Edit an existing master medicine from the Super Admin "Master catalogs" page.

Columns:
  generic name | strength | form | schedule | default units per pack | billing mode | GST % | category
  form      : Tablet, Capsule, Sachet, Suppository, Patch, Syrup, Suspension, Injection, Drops, Ointment,
              Cream, Gel, Lotion, Inhaler, Spray, Powder, Other
  schedule  : otc, h, h1, x
  billing   : per_pack (sold by the strip/box) or per_unit (sold by the tablet/bottle/vial)
  GST %     : 0, 5, 12, 18 or 28.  Please confirm the right GST slab for each medicine with your accountant.
Real pack sizes differ by brand, so the hospital can change the units per pack when it adds a medicine.
"""

HSN_CODE = "3004"      # medicaments in measured doses; change per medicine in the tuple list below if needed

# generic, strength, form, schedule, default pack, billing mode, GST %, category
_ROWS = [
    ("Paracetamol", "500mg", "Tablet", "otc", 10, "per_pack", 5, "Analgesic / Antipyretic"),
    ("Paracetamol", "125mg/5ml", "Syrup", "otc", 1, "per_unit", 5, "Analgesic / Antipyretic"),
    ("Ibuprofen", "400mg", "Tablet", "otc", 10, "per_pack", 5, "Analgesic / Anti-inflammatory"),
    ("Cetirizine", "10mg", "Tablet", "otc", 10, "per_pack", 5, "Antihistamine"),
    ("Pantoprazole", "40mg", "Tablet", "h", 15, "per_pack", 5, "Antacid / PPI"),
    ("Amoxicillin", "500mg", "Capsule", "h", 10, "per_pack", 5, "Antibiotic"),
    ("Amoxicillin + Clavulanic Acid", "500mg/125mg", "Tablet", "h", 10, "per_pack", 5, "Antibiotic"),
    ("Azithromycin", "500mg", "Tablet", "h", 3, "per_pack", 5, "Antibiotic"),
    ("Ciprofloxacin", "500mg", "Tablet", "h", 10, "per_pack", 5, "Antibiotic"),
    ("Levofloxacin", "500mg", "Tablet", "h1", 5, "per_pack", 5, "Antibiotic"),
    ("Metformin", "500mg", "Tablet", "h", 10, "per_pack", 5, "Antidiabetic"),
    ("Amlodipine", "5mg", "Tablet", "h", 10, "per_pack", 5, "Antihypertensive"),
    ("Atorvastatin", "10mg", "Tablet", "h", 10, "per_pack", 5, "Statin"),
    ("Telmisartan", "40mg", "Tablet", "h", 10, "per_pack", 5, "Antihypertensive"),
    ("Ondansetron", "4mg", "Tablet", "h", 10, "per_pack", 5, "Antiemetic"),
    ("Ceftriaxone", "1g", "Injection", "h1", 1, "per_unit", 5, "Antibiotic"),
    ("Salbutamol", "100mcg", "Inhaler", "h", 1, "per_unit", 5, "Respiratory"),
    ("Alprazolam", "0.25mg", "Tablet", "h1", 10, "per_pack", 5, "Sedative / Anxiolytic"),
    ("Tramadol", "50mg", "Capsule", "h1", 10, "per_pack", 5, "Analgesic (opioid)"),
    ("Methylphenidate", "10mg", "Tablet", "x", 10, "per_pack", 5, "CNS stimulant"),
]

MASTER_MEDICINES = [
    {"generic_name": g, "strength": s, "dosage_form": f, "schedule": sch, "default_pack_size": pack,
     "default_billing_mode": mode, "gst_percent": gst, "hsn_code": HSN_CODE, "category": cat}
    for (g, s, f, sch, pack, mode, gst, cat) in _ROWS
]