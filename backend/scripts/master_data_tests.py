"""MASTER TEST LIST (platform-wide). One dict per test; no prices (hospitals set their own price).
Add a test by copying one block and changing it, then run:  python scripts/load_master_catalog.py
The loader only ADDS tests that are not already in the master list (matched by name); it never changes or deletes one.
Edit an existing master test from the Super Admin "Master catalogs" page instead.
Never add HIV or radiology tests here. Reference ranges are typical adult ranges: please review them for your labs.

Keys (same as the Add master test form):
  test_name, category, aliases, required_tube, fasting_required, turnaround_hours, is_panel, purpose
  single test: unit, reference_range_male, reference_range_female, critical_low, critical_high
  panel:       parameters = [P(name, unit, male range, female range, critical low, critical high), ...]
"""


def P(name, unit="", male="", female="", low=None, high=None):
    return {"name": name, "unit": unit, "reference_range_male": male, "reference_range_female": female,
            "critical_low": low, "critical_high": high}


MASTER_TESTS = [
    {"test_name": "Complete Blood Count (CBC)", "category": "Haematology", "aliases": "CBC, Hemogram, Complete Blood Picture",
     "required_tube": "EDTA (purple top)", "fasting_required": False, "turnaround_hours": 4, "is_panel": True,
     "parameters": [
         P("Haemoglobin", "g/dL", "13.0-17.0", "12.0-15.0", 7.0, 20.0),
         P("Total Leucocyte Count", "/cumm", "4000-11000", "4000-11000", 2000.0, 30000.0),
         P("RBC Count", "million/cumm", "4.5-5.5", "3.8-4.8"),
         P("Haematocrit (PCV)", "%", "40-50", "36-46"),
         P("MCV", "fL", "83-101", "83-101"),
         P("MCH", "pg", "27-32", "27-32"),
         P("MCHC", "g/dL", "31.5-34.5", "31.5-34.5"),
         P("Platelet Count", "lakh/cumm", "1.5-4.1", "1.5-4.1", 0.5, 10.0),
     ]},
    {"test_name": "Lipid Profile", "category": "Biochemistry", "aliases": "Lipid Panel, Cholesterol Profile",
     "required_tube": "Plain (red top)", "fasting_required": True, "turnaround_hours": 6, "is_panel": True,
     "parameters": [
         P("Total Cholesterol", "mg/dL", "<200", "<200"),
         P("Triglycerides", "mg/dL", "<150", "<150"),
         P("HDL Cholesterol", "mg/dL", ">40", ">50"),
         P("LDL Cholesterol", "mg/dL", "<100", "<100"),
         P("VLDL Cholesterol", "mg/dL", "<30", "<30"),
     ]},
    {"test_name": "Liver Function Test (LFT)", "category": "Biochemistry", "aliases": "LFT, Liver Panel",
     "required_tube": "Plain (red top)", "fasting_required": False, "turnaround_hours": 6, "is_panel": True,
     "parameters": [
         P("Total Bilirubin", "mg/dL", "0.3-1.2", "0.3-1.2"),
         P("Direct Bilirubin", "mg/dL", "0.0-0.3", "0.0-0.3"),
         P("Indirect Bilirubin", "mg/dL", "0.2-0.9", "0.2-0.9"),
         P("SGOT (AST)", "U/L", "5-40", "5-40"),
         P("SGPT (ALT)", "U/L", "7-56", "7-45"),
         P("Alkaline Phosphatase (ALP)", "U/L", "44-147", "44-147"),
         P("Total Protein", "g/dL", "6.0-8.3", "6.0-8.3"),
         P("Albumin", "g/dL", "3.5-5.2", "3.5-5.2"),
         P("Globulin", "g/dL", "2.0-3.5", "2.0-3.5"),
     ]},
    {"test_name": "Kidney Function Test (KFT)", "category": "Biochemistry", "aliases": "KFT, RFT, Renal Function Test",
     "required_tube": "Plain (red top)", "fasting_required": False, "turnaround_hours": 6, "is_panel": True,
     "parameters": [
         P("Blood Urea", "mg/dL", "15-45", "15-45"),
         P("Serum Creatinine", "mg/dL", "0.7-1.3", "0.6-1.1", None, 10.0),
         P("Serum Uric Acid", "mg/dL", "3.5-7.2", "2.6-6.0"),
         P("Sodium", "mmol/L", "135-145", "135-145", 120.0, 160.0),
         P("Potassium", "mmol/L", "3.5-5.1", "3.5-5.1", 2.5, 6.5),
     ]},
    {"test_name": "Thyroid Profile (T3, T4, TSH)", "category": "Biochemistry", "aliases": "Thyroid Function Test, TFT",
     "required_tube": "Plain (red top)", "fasting_required": False, "turnaround_hours": 8, "is_panel": True,
     "parameters": [
         P("Total T3", "ng/dL", "80-200", "80-200"),
         P("Total T4", "ug/dL", "5.1-14.1", "5.1-14.1"),
         P("TSH", "uIU/mL", "0.4-4.2", "0.4-4.2"),
     ]},
    {"test_name": "Blood Sugar (Fasting)", "category": "Biochemistry", "aliases": "FBS, Fasting Blood Glucose",
     "required_tube": "Fluoride (grey top)", "fasting_required": True, "turnaround_hours": 2, "is_panel": False,
     "unit": "mg/dL", "reference_range_male": "70-100", "reference_range_female": "70-100",
     "critical_low": 40.0, "critical_high": 500.0},
    {"test_name": "Blood Sugar (Post Prandial)", "category": "Biochemistry", "aliases": "PPBS, PP Blood Glucose",
     "required_tube": "Fluoride (grey top)", "fasting_required": False, "turnaround_hours": 2, "is_panel": False,
     "unit": "mg/dL", "reference_range_male": "70-140", "reference_range_female": "70-140",
     "critical_low": 40.0, "critical_high": 500.0},
    {"test_name": "Blood Sugar (Random)", "category": "Biochemistry", "aliases": "RBS, Random Blood Glucose",
     "required_tube": "Fluoride (grey top)", "fasting_required": False, "turnaround_hours": 2, "is_panel": False,
     "unit": "mg/dL", "reference_range_male": "70-140", "reference_range_female": "70-140",
     "critical_low": 40.0, "critical_high": 500.0},
    {"test_name": "HbA1c", "category": "Biochemistry", "aliases": "Glycosylated Haemoglobin, Glycated Hb",
     "required_tube": "EDTA (purple top)", "fasting_required": False, "turnaround_hours": 6, "is_panel": False,
     "unit": "%", "reference_range_male": "4.0-5.6", "reference_range_female": "4.0-5.6"},
    {"test_name": "Serum Creatinine", "category": "Biochemistry", "aliases": "Creatinine",
     "required_tube": "Plain (red top)", "fasting_required": False, "turnaround_hours": 4, "is_panel": False,
     "unit": "mg/dL", "reference_range_male": "0.7-1.3", "reference_range_female": "0.6-1.1", "critical_high": 10.0},
    {"test_name": "Blood Urea", "category": "Biochemistry", "aliases": "Urea",
     "required_tube": "Plain (red top)", "fasting_required": False, "turnaround_hours": 4, "is_panel": False,
     "unit": "mg/dL", "reference_range_male": "15-45", "reference_range_female": "15-45"},
    {"test_name": "Serum Uric Acid", "category": "Biochemistry", "aliases": "Uric Acid",
     "required_tube": "Plain (red top)", "fasting_required": False, "turnaround_hours": 4, "is_panel": False,
     "unit": "mg/dL", "reference_range_male": "3.5-7.2", "reference_range_female": "2.6-6.0"},
    {"test_name": "SGPT (ALT)", "category": "Biochemistry", "aliases": "ALT, Alanine Transaminase",
     "required_tube": "Plain (red top)", "fasting_required": False, "turnaround_hours": 4, "is_panel": False,
     "unit": "U/L", "reference_range_male": "7-56", "reference_range_female": "7-45"},
    {"test_name": "Thyroid Stimulating Hormone (TSH)", "category": "Biochemistry", "aliases": "TSH",
     "required_tube": "Plain (red top)", "fasting_required": False, "turnaround_hours": 8, "is_panel": False,
     "unit": "uIU/mL", "reference_range_male": "0.4-4.2", "reference_range_female": "0.4-4.2"},
    {"test_name": "Vitamin D (25-OH)", "category": "Biochemistry", "aliases": "Vitamin D3, 25 Hydroxy Vitamin D",
     "required_tube": "Plain (red top)", "fasting_required": False, "turnaround_hours": 24, "is_panel": False,
     "unit": "ng/mL", "reference_range_male": "30-100", "reference_range_female": "30-100"},
    {"test_name": "Vitamin B12", "category": "Biochemistry", "aliases": "Cyanocobalamin",
     "required_tube": "Plain (red top)", "fasting_required": False, "turnaround_hours": 24, "is_panel": False,
     "unit": "pg/mL", "reference_range_male": "200-900", "reference_range_female": "200-900"},
    {"test_name": "Erythrocyte Sedimentation Rate (ESR)", "category": "Haematology", "aliases": "ESR",
     "required_tube": "EDTA (purple top)", "fasting_required": False, "turnaround_hours": 2, "is_panel": False,
     "unit": "mm/hr", "reference_range_male": "0-15", "reference_range_female": "0-20"},
    {"test_name": "Urine Routine", "category": "Clinical Pathology", "aliases": "Urine R/M, Urine Routine and Microscopy",
     "required_tube": "Sterile urine container", "fasting_required": False, "turnaround_hours": 2, "is_panel": False},
    {"test_name": "Widal Test", "category": "Serology", "aliases": "Typhoid Widal",
     "required_tube": "Plain (red top)", "fasting_required": False, "turnaround_hours": 4, "is_panel": False,
     "reference_range_male": "Negative", "reference_range_female": "Negative"},
    {"test_name": "Dengue NS1 Antigen", "category": "Serology", "aliases": "Dengue NS1",
     "required_tube": "Plain (red top)", "fasting_required": False, "turnaround_hours": 4, "is_panel": False,
     "reference_range_male": "Negative", "reference_range_female": "Negative"},
]