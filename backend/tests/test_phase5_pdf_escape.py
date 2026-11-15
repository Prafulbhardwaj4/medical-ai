import json
from datetime import datetime
from types import SimpleNamespace

import pdfplumber
import pytest

from app.services import pdf_service

EVIL_NAME = "<b>"
EVIL_IMG = "<img src=http://x/y.png>"


def _pdf_text(path: str) -> str:
    with pdfplumber.open(path) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


def _hospital(name=EVIL_IMG):
    return SimpleNamespace(
        name=name, address=EVIL_NAME, city="Ambala", state="Haryana", phone="9999999999",
        logo_base64=None, emails=None, contact_numbers=None, gstin=None,
        clinical_establishment_reg_no=None, drug_licence_no=None, hospital_code="HOSP1",
    )


def _doctor(hospital=None):
    return SimpleNamespace(
        title="Dr.", name=EVIL_NAME, specialization=EVIL_IMG, registration_number="REG<1>",
        clinic_name=EVIL_IMG, hospital=hospital,
    )


def _patient(name=EVIL_NAME):
    return SimpleNamespace(
        name=name, age=30, gender="male", blood_group=None, phone="+919999999999",
        patient_uid="P-1", address=EVIL_IMG,
    )


def _consultation():
    return SimpleNamespace(
        chief_complaint=EVIL_NAME, vitals="{}", diagnosis=EVIL_IMG,
        medicines=json.dumps([{"name": EVIL_NAME, "brand_name": EVIL_IMG, "dosage": "<i>1</i>",
                               "frequency": "<br/>", "duration": "<u>3d</u>", "schedule": "otc"}]),
        ordered_tests="[]", tests="[]", ordered_radiology="[]",
        advice=EVIL_NAME, followup=EVIL_IMG,
    )


def test_escape_helper():
    assert pdf_service._esc(None) == ""
    assert pdf_service._esc("<b>&</b>") == "&lt;b&gt;&amp;&lt;/b&gt;"
    assert pdf_service._esc(12) == "12"


def test_patient_summary_line_is_escaped():
    line = pdf_service._patient_summary_line(_patient(EVIL_IMG))
    assert "<img" not in line.lower()
    assert "&lt;" in line


def test_hospital_detail_lines_do_not_parse_markup():
    style = pdf_service.ParagraphStyle("t")
    lines = pdf_service._hospital_detail_lines(_hospital(), style)
    for p in lines:
        assert "<img" not in p.text.lower()


def test_prescription_pdf_shows_markup_as_plain_text(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_service, "PRESCRIPTIONS_DIR", str(tmp_path))
    for hospital in (None, _hospital()):
        path = pdf_service.generate_prescription_pdf(
            _doctor(hospital), _patient(), _consultation(), "TOK-1", verify_hash="abc123")
        text = _pdf_text(path).lower()
        assert "<b>" in text, "patient/doctor name must be printed literally"
        assert "<img src=http://x/y.png>" in text


def test_prescription_pdf_with_img_patient_name(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_service, "PRESCRIPTIONS_DIR", str(tmp_path))
    path = pdf_service.generate_prescription_pdf(
        _doctor(_hospital()), _patient(EVIL_IMG), _consultation(), "TOK-2", verify_hash="abc123")
    assert "<img src=http://x/y.png>" in _pdf_text(path).lower()


def _order():
    return SimpleNamespace(
        id=7, test_name=EVIL_IMG, result_data=json.dumps({"value": "5", "notes": EVIL_NAME}),
        verified_at=datetime(2026, 1, 2, 10, 0), collected_at=None, accession_number="ACC<1>",
        accessioned_at=None, report_reference="REF<1>", is_mlc_sample=False,
        fasting_confirmed=True, drawn_from_iv_line=False, sample_condition_caveat=EVIL_IMG,
        amended_at=datetime(2026, 1, 3, 10, 0), amendment_reason=EVIL_NAME, result_snapshot=None,
        mlc_case_type=None, mlc_reference_number=None,
    )


def test_lab_report_pdf_escapes(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_service, "REPORTS_DIR", str(tmp_path))
    path = pdf_service.generate_test_report_pdf(
        _order(), _patient(), None, _doctor(), None, _hospital(),
        verify_hash="abc123", token_number="TOK<9>", report_created_by=_doctor())
    text = _pdf_text(path).lower()
    assert "<img src=http://x/y.png>" in text
    assert "<b>" in text


def test_combined_lab_report_pdf_escapes(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_service, "REPORTS_DIR", str(tmp_path))
    payload = [{
        "test_name": EVIL_IMG, "report_reference": "R<1>", "verified_at": datetime(2026, 1, 2, 10, 0),
        "collected_at": None, "accession_number": "A<1>", "accessioned_at": None,
        "fasting_confirmed": True, "drawn_from_iv_line": False, "sample_condition_caveat": EVIL_NAME,
        "amended_at": datetime(2026, 1, 3, 10, 0), "amendment_reason": EVIL_NAME, "notes": EVIL_NAME,
        "is_nabl_accredited": False,
        "rows": [{"name": EVIL_NAME, "value": "5", "unit": "g", "range": "1-9", "flag": None}],
    }]
    path = pdf_service.generate_combined_test_report_pdf(
        "7_1-2", payload, _patient(), _doctor(), None, _hospital(), verify_hash="abc123", token_number="T<1>")
    assert "<img src=http://x/y.png>" in _pdf_text(path).lower()